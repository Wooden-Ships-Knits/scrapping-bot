"""Store discovery, offline: the search APIs are a FakeSearchApi, the agent a LiteLLM
mock response. Answers are written in each API's documented shape; nothing here is a
recorded response."""

import csv
import functools
import json

import litellm
import pytest
from litellm.exceptions import AuthenticationError
from pydantic import SecretStr

from scrapebot.cli import main
from scrapebot.discover import DiscoverConfig, run_discover
from scrapebot.discover.agent import AgentSource, stores_in_text
from scrapebot.discover.merge import (
    Candidate,
    FoundStore,
    fold_by_website,
    merge,
    social_profile,
    store_website,
)
from scrapebot.discover.paid import ApiError, BudgetReached, PaidApi
from scrapebot.discover.places import PlacesSource, to_candidate
from scrapebot.discover.search import (
    WebsiteLookup,
    looks_like,
    place_in,
    profile_name,
    site_name,
    tavily_search,
    website_in,
)
from scrapebot.inputs.readers import read_file
from scrapebot.inputs.resolve import resolve
from scrapebot.keys import load_keys, redact
from tests.fakes import FakeSearchApi

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
TAVILY_URL = "https://api.tavily.com/search"
GOOGLE_KEY = "AIzaFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE12"
TAVILY_KEY = "tvly-FAKEFAKEFAKEFAKEFAKE1234"


def place(name, website="", city="Boulder", state="CO", zip_="80302", number="1200", **extra):
    return {
        "id": f"place-{name}",
        "displayName": {"text": name},
        "formattedAddress": f"{number} Pearl St, {city}, {state} {zip_}, USA",
        "addressComponents": [
            {"longText": number, "shortText": number, "types": ["street_number"]},
            {"longText": "Pearl Street", "shortText": "Pearl St", "types": ["route"]},
            {"longText": city, "shortText": city, "types": ["locality", "political"]},
            {"longText": "Colorado", "shortText": state, "types": ["administrative_area_level_1"]},
            {"longText": zip_, "shortText": zip_, "types": ["postal_code"]},
            {"longText": "United States", "shortText": "US", "types": ["country"]},
        ],
        "websiteUri": website,
        "nationalPhoneNumber": "(303) 555-0100",
        "businessStatus": "OPERATIONAL",
        **extra,
    }


def result(title, url, content=""):
    return {"title": title, "url": url, "content": content, "score": 0.9}


def config(tmp_path, **overrides) -> DiscoverConfig:
    data = {
        "locations": ["Boulder, CO"],
        "brands": [],
        "exclude_domains": ["wooden-ships.com", "vogue.com"],
        "google_places": {"queries": ["sweater boutique"], "max_pages": 2},
        "web_search": {"queries": ["knitwear boutique online"], "brand_queries": []},
        "social_search": {"queries": ['site:instagram.com boutique sweaters "{location}"']},
        "ai_agent": {"enabled": False},
        "out_dir": tmp_path / "discover",
        "cache_dir": tmp_path / "cache",
    }
    data.update(overrides)
    return DiscoverConfig.model_validate(data)


def keys(**names):
    return {name: SecretStr(value) for name, value in names.items()}


# --- the paid API client ---------------------------------------------------------


def test_paid_answers_are_cached_without_the_key(tmp_path):
    api_fake = FakeSearchApi({TAVILY_URL: lambda body: (200, {"results": []})})
    api = PaidApi("web_search", tmp_path, max_requests=5, transport=api_fake, min_interval=0)
    headers = {"Authorization": f"Bearer {TAVILY_KEY}"}
    api.post(TAVILY_URL, {"query": "a"}, headers)
    api.post(TAVILY_URL, {"query": "a"}, headers)
    assert (api.sent, api.cached, len(api_fake.calls)) == (1, 1, 1)
    cached = "".join(p.read_text() for p in (tmp_path / "web_search").glob("*.json"))
    assert TAVILY_KEY not in cached


def test_paid_failures_are_retried_and_never_cached(tmp_path):
    answers = iter([(503, "busy"), (200, {"results": []})])
    api = PaidApi(
        "x",
        tmp_path,
        max_requests=5,
        transport=FakeSearchApi({TAVILY_URL: lambda body: next(answers)}),
        min_interval=0,
        sleep=lambda s: None,
    )
    assert api.post(TAVILY_URL, {"query": "a"}, {}) == {"results": []}
    assert api.sent == 2


def test_paid_refusal_stops_with_the_key_masked(tmp_path):
    echo = f'{{"error": "invalid key {GOOGLE_KEY}"}}'
    api = PaidApi(
        "google_places",
        tmp_path,
        max_requests=5,
        transport=FakeSearchApi({PLACES_URL: lambda body: (403, echo)}),
        min_interval=0,
    )
    with pytest.raises(ApiError) as caught:
        api.post(PLACES_URL, {}, {"X-Goog-Api-Key": GOOGLE_KEY})
    assert "HTTP 403" in str(caught.value)
    assert GOOGLE_KEY not in str(caught.value)
    assert not list(tmp_path.rglob("*.json")), "a refusal is not cached"


def test_paid_requests_stop_at_the_cap(tmp_path):
    fake = FakeSearchApi({TAVILY_URL: lambda body: (200, {"results": []})})
    api = PaidApi("x", tmp_path, max_requests=1, transport=fake, min_interval=0)
    api.post(TAVILY_URL, {"query": "a"}, {})
    with pytest.raises(BudgetReached):
        api.post(TAVILY_URL, {"query": "b"}, {})
    assert len(fake.calls) == 1


# --- sources ---------------------------------------------------------------------


def test_a_place_becomes_a_candidate():
    cand = to_candidate(place("Cedar & Hyde", "https://cedarandhyde.com/"), "sweater boutique")
    assert cand is not None
    assert (cand.name, cand.website, cand.address) == (
        "Cedar & Hyde",
        "https://cedarandhyde.com/",
        "1200 Pearl Street",
    )
    assert (cand.city, cand.state, cand.postal_code, cand.country) == (
        "Boulder",
        "CO",
        "80302",
        "US",
    )
    assert to_candidate({"displayName": {}}, "q") is None


def test_places_pages_through_results_and_asks_only_for_needed_fields(tmp_path):
    pages = {
        None: {"places": [place("A Shop", "https://ashop.com")], "nextPageToken": "t2"},
        "t2": {"places": [place("B Shop", "https://bshop.com", number="9")]},
    }
    fake = FakeSearchApi({PLACES_URL: lambda body: (200, pages[body.get("pageToken")])})
    cfg = config(tmp_path, locations=["Boulder, CO", "Toronto, ON"])
    source = PlacesSource(cfg, GOOGLE_KEY, PaidApi("p", tmp_path, 10, fake, min_interval=0))
    source.run()
    assert [c.name for c in source.found] == ["A Shop", "B Shop", "A Shop", "B Shop"]
    _, headers, body = fake.calls[0]
    assert body == {
        "textQuery": "sweater boutique in Boulder, CO",
        "pageSize": 20,
        "regionCode": "US",
    }
    assert fake.calls[2][2]["regionCode"] == "CA", "Toronto is searched in Canada"
    mask = headers["X-Goog-FieldMask"]
    assert "places.websiteUri" in mask
    assert "rating" not in mask
    assert "location" not in mask


def test_tavily_sends_site_filters_as_include_domains(tmp_path):
    fake = FakeSearchApi(
        {TAVILY_URL: lambda body: (200, {"results": [result("T", "https://x.com")]})}
    )
    api = PaidApi("t", tmp_path, 10, fake, min_interval=0)
    tavily_search(
        api, "https://api.tavily.com", TAVILY_KEY, 'site:instagram.com boutique "Boulder"', "US"
    )
    tavily_search(api, "https://api.tavily.com", TAVILY_KEY, "knit boutique", "CA")
    assert fake.calls[0][2] == {
        "query": 'boutique "Boulder"',
        "max_results": 20,
        "include_domains": ["instagram.com"],
    }
    assert fake.calls[1][2]["country"] == "canada"
    assert fake.calls[1][1]["Authorization"] == f"Bearer {TAVILY_KEY}"


def test_search_result_names_and_profiles():
    assert site_name("Sweaters | Cedar & Hyde Mercantile") == "Cedar & Hyde Mercantile"
    assert profile_name("Cedar & Hyde (@cedarandhyde) • Instagram photos and videos", "x") == (
        "Cedar & Hyde"
    )
    assert profile_name("Instagram", "cedarandhyde") == "cedarandhyde"
    assert website_in("Women's boutique. Shop cedarandhyde.com. Boulder, CO") == (
        "https://cedarandhyde.com"
    )
    assert website_in("follow us on instagram.com/x") == ""
    assert place_in("Boutique in Boulder, CO since 2010") == ("Boulder", "CO")


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        ("https://www.instagram.com/Cedar.Hyde/?hl=en", ("instagram", "cedar.hyde")),
        ("https://www.instagram.com/p/C1234/", None),
        ("https://m.facebook.com/CedarAndHyde/about", ("facebook", "cedarandhyde")),
        ("https://www.facebook.com/groups/knitters", None),
        ("https://www.facebook.com/profile.php?id=123", ("facebook", "id:123")),
        ("https://cedarandhyde.com", None),
    ],
)
def test_social_profiles(link, expected):
    got = social_profile(link)
    assert (got[:2] if got else None) == expected


def test_only_a_store_s_own_site_counts_as_its_website():
    assert store_website("https://shop.cedarandhyde.com/collections") == "cedarandhyde.com"
    assert store_website("https://www.etsy.com/shop/x") == ""
    assert store_website("https://www.yelp.com/biz/x") == ""
    assert store_website("https://linktr.ee/x") == ""
    assert store_website("https://vogue.com/x", frozenset({"vogue.com"})) == ""


# --- merging ---------------------------------------------------------------------


def test_sightings_of_one_store_merge_by_website_profile_and_place():
    maps = Candidate(
        name="Cedar & Hyde",
        source="google_places",
        website="https://www.cedarandhyde.com/",
        address="1200 Pearl Street",
        city="Boulder",
        state="CO",
        postal_code="80302",
        country="US",
    )
    web = Candidate(
        name="Shop | Cedar and Hyde",
        source="web_search",
        website="https://cedarandhyde.com/sweaters",
    )
    social = Candidate(
        name="Cedar & Hyde",
        source="social_search",
        instagram="https://www.instagram.com/cedarandhyde/",
        city="Boulder",
        state="CO",
    )
    agent = Candidate(
        name="Cedar and Hyde",
        source="ai_agent",
        instagram="@cedarandhyde",
        website="https://www.instagram.com/cedarandhyde",
    )
    [store] = merge([web, social, agent, maps], ["US", "CA"], [])
    assert store.name == "Cedar & Hyde", "the Maps listing name wins"
    assert store.website == "https://cedarandhyde.com", "the first website seen is kept"
    assert store.instagram == "https://www.instagram.com/cedarandhyde/"
    assert store.sources == ["web_search", "social_search", "ai_agent", "google_places"]
    assert len(store.locations) == 1, "the town-only sighting gave way to the full address"
    assert store.locations[0].address == "1200 Pearl Street"
    assert store.store_id == "cedarandhyde.com"


def test_merge_drops_what_cannot_be_a_store_to_visit():
    stores = merge(
        [
            Candidate(name="Abroad", source="ai_agent", website="https://abroad.fr", country="FR"),
            Candidate(
                name="Closed",
                source="google_places",
                city="Boulder",
                state="CO",
                business_status="CLOSED_PERMANENTLY",
            ),
            Candidate(name="Own Site", source="web_search", website="https://wooden-ships.com"),
            Candidate(name="Just A Name", source="ai_agent"),
            Candidate(
                name="Etsy Seller",
                source="ai_agent",
                website="https://etsy.com/shop/x",
                city="Austin",
                state="TX",
            ),
        ],
        ["US", "CA"],
        ["wooden-ships.com"],
    )
    assert [(s.name, s.website) for s in stores] == [("Etsy Seller", "")], (
        "a marketplace link is not a website, but the town is enough to look one up"
    )


# --- the agent -------------------------------------------------------------------

AGENT_ANSWER = json.dumps(
    [
        {"name": "Cedar & Hyde", "website": "https://cedarandhyde.com", "city": "Boulder",
         "state": "co", "country": "us", "note": "multi-brand, sweaters"},
        {"name": "", "website": "https://nameless.com"},
        "not an object",
    ]
)  # fmt: skip


def test_store_lists_are_read_from_fenced_wrapped_or_plain_answers():
    fenced = stores_in_text(f"Here you go:\n```json\n{AGENT_ANSWER}\n```")
    wrapped = stores_in_text('{"stores": [{"name": "A"}]}')
    assert fenced is not None
    assert wrapped is not None
    assert [s.name for s in fenced] == ["Cedar & Hyde"]
    assert [s.name for s in wrapped] == ["A"]
    assert stores_in_text("I could not find any stores.") is None


def agent_config(tmp_path):
    return config(
        tmp_path,
        ai_agent={"model": "gemini/gemini-2.5-flash", "areas": ["Colorado"], "budget_usd": 1},
    )


def test_the_agent_asks_with_web_search_records_cost_and_caches(tmp_path):
    seen = []

    def completion(**kwargs):
        seen.append(kwargs)
        return litellm.completion(mock_response=AGENT_ANSWER, **kwargs)

    cfg = agent_config(tmp_path)
    agent = AgentSource(cfg, keys(gemini="gm-key-123456"), tmp_path / "cache", completion)
    agent.run()
    assert [(c.name, c.state, c.country) for c in agent.found] == [("Cedar & Hyde", "CO", "US")]
    assert seen[0]["web_search_options"] == {"search_context_size": "medium"}
    assert seen[0]["api_key"] == "gm-key-123456"
    assert [c.status for c in agent.calls] == ["ok"]

    again = AgentSource(cfg, keys(gemini="gm-key-123456"), tmp_path / "cache", completion)
    again.run()
    assert (len(seen), again.cached, len(again.found)) == (1, 1, 1), "the second ask is free"


def test_a_refused_agent_key_stops_the_agent(tmp_path):
    def completion(**kwargs):
        raise AuthenticationError("bad key", llm_provider="gemini", model="gemini-2.5-flash")

    cfg = agent_config(tmp_path)
    agent = AgentSource(cfg, keys(gemini="gm-key-123456"), tmp_path / "cache", completion)
    with pytest.raises(ApiError, match="API key ditolak"):
        agent.run()


# --- website lookup ---------------------------------------------------------------


def test_a_lookup_result_must_carry_the_store_s_name_or_handle():
    store = FoundStore(name="Cedar & Hyde", instagram="https://www.instagram.com/cedarhyde.co/")
    assert looks_like(store, "https://cedarandhyde.com", "Home")
    assert looks_like(store, "https://shop-ch.com", "Cedar & Hyde | Boulder boutique")
    assert not looks_like(store, "https://randomshop.com", "Sweaters")
    assert not looks_like(store, "https://www.yelp.com/biz/cedar-and-hyde", "Cedar & Hyde - Yelp")


def test_lookup_skips_directories_and_takes_the_matching_site(tmp_path):
    answer = {
        "results": [
            result("Cedar & Hyde - Yelp", "https://www.yelp.com/biz/cedar-and-hyde-boulder"),
            result("Cedar & Hyde Mercantile", "https://cedarandhyde.com/pages/about"),
        ]
    }
    fake = FakeSearchApi({TAVILY_URL: lambda body: (200, answer)})
    lookup = WebsiteLookup(
        config(tmp_path), TAVILY_KEY, PaidApi("r", tmp_path, 5, fake, min_interval=0)
    )
    store = merge(
        [Candidate(name="Cedar & Hyde", source="social_search", city="Boulder", state="CO")],
        ["US"],
        [],
    )[0]
    assert lookup.find(store) == "https://cedarandhyde.com"
    assert fake.calls[0][2]["query"] == '"Cedar & Hyde" Boulder CO official website'


# --- a whole discovery -------------------------------------------------------------


def search_routes():
    def places(body):
        return 200, {
            "places": [
                place("Cedar & Hyde", "https://cedarandhyde.com/"),
                place("No Site Knits", number="5"),
            ]
        }

    def tavily(body):
        query = body["query"]
        if "official website" in query:
            hit = "No Site Knits" in query
            url = "https://nositeknits.com" if hit else "https://other.com"
            return 200, {"results": [result("No Site Knits", url)]}
        if body.get("include_domains") == ["instagram.com"]:
            return 200, {
                "results": [
                    result(
                        "Cedar & Hyde (@cedarandhyde) • Instagram photos and videos",
                        "https://www.instagram.com/cedarandhyde/",
                        "Sweaters and knitwear. cedarandhyde.com Boulder, CO",
                    )
                ]
            }
        return 200, {
            "results": [
                result("Knitwear | Loop Boutique", "https://loopboutique.com/collections/knitwear"),
                result("Best boutiques - Vogue", "https://vogue.com/article/boutiques"),
            ]
        }

    return FakeSearchApi({PLACES_URL: places, TAVILY_URL: tavily})


def test_a_discovery_writes_a_links_file_scrapebot_run_reads(tmp_path):
    fake = search_routes()
    cfg = config(tmp_path, countries=["US"])
    got = run_discover(cfg, keys(google_places=GOOGLE_KEY, tavily=TAVILY_KEY), transport=fake)

    by_name = {s.name: s for s in got.stores}
    assert set(by_name) == {"Cedar & Hyde", "No Site Knits", "Loop Boutique"}, "Vogue is excluded"
    assert by_name["Cedar & Hyde"].sources == ["google_places", "social_search"]
    assert (by_name["No Site Knits"].website, by_name["No Site Knits"].website_source) == (
        "https://nositeknits.com",
        "lookup",
    )
    status = {r.name: r.status for r in got.sources}
    assert status == {
        "google_places": "ok",
        "web_search": "ok",
        "social_search": "ok",
        "ai_agent": "disabled",
    }

    records = read_file(got.stores_csv)
    resolution = resolve(records)
    assert sorted(t.domain for t in resolution.targets) == [
        "cedarandhyde.com",
        "loopboutique.com",
        "nositeknits.com",
    ]
    assert {r.meta["name"] for r in records} == set(by_name), "store details travel as metadata"

    written = got.root.rglob("*")
    text = "".join(p.read_text() for p in written if p.is_file())
    assert GOOGLE_KEY not in text
    assert TAVILY_KEY not in text
    report = json.loads(got.report_path.read_text())
    assert report["stores_with_website"] == 3
    assert report["sources"][0]["requests_sent"] == 1


def test_a_source_without_its_key_is_skipped_and_the_rest_run(tmp_path):
    got = run_discover(config(tmp_path), keys(tavily=TAVILY_KEY), transport=search_routes())
    status = {r.name: r.status for r in got.sources}
    assert status["google_places"] == "no_api_key"
    assert status["web_search"] == "ok"
    assert got.stores, "Tavily alone still finds stores"


def test_only_runs_the_named_steps(tmp_path):
    fake = search_routes()
    got = run_discover(
        config(tmp_path),
        keys(google_places=GOOGLE_KEY, tavily=TAVILY_KEY),
        only=["web_search"],
        transport=fake,
    )
    assert {r.name for r in got.sources if r.status == "ok"} == {"web_search"}
    assert all(
        url == TAVILY_URL and "official website" not in body["query"] for url, _, body in fake.calls
    )


# --- keys and the command line -------------------------------------------------------


def test_search_keys_come_from_env_and_are_masked(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"TAVILY_API_KEY={TAVILY_KEY}\nGOOGLE_MAPS_API_KEY={GOOGLE_KEY}\n")
    loaded = load_keys(env)
    assert loaded["tavily"].get_secret_value() == TAVILY_KEY
    assert loaded["google_places"].get_secret_value() == GOOGLE_KEY
    assert TAVILY_KEY not in redact(f"key {TAVILY_KEY}")
    assert "tvly-" not in redact("Authorization: Bearer tvly-unregisteredkey12345678")


def test_cli_discover_without_keys_fails_but_writes_an_empty_links_file(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "discover.yaml"
    cfg.write_text("locations: [Boulder, CO]\nai_agent: {enabled: false}\n")
    assert main(["discover", "-c", str(cfg), "--out", str(tmp_path / "out")]) == 1
    captured = capsys.readouterr()
    assert "no_api_key" in captured.out
    assert "No source ran" in captured.err
    [stores_csv] = (tmp_path / "out").rglob("stores.csv")
    with stores_csv.open() as fh:
        assert (csv.DictReader(fh).fieldnames or [""])[0] == "website"


def test_cli_discover_refuses_an_unknown_step(tmp_path, capsys):
    cfg = tmp_path / "discover.yaml"
    cfg.write_text("{}\n")
    assert main(["discover", "-c", str(cfg), "--only", "maps"]) == 2
    assert "unknown step" in capsys.readouterr().err


def test_the_example_config_is_valid():
    from pathlib import Path

    from scrapebot.discover import load_discover_config

    example = Path(__file__).resolve().parents[2] / "discover.example.yaml"
    cfg = load_discover_config(example)
    assert cfg.locations
    assert cfg.brands
    assert cfg.google_places.queries


# --- fixes from review ---------------------------------------------------------------


def test_a_broken_cache_file_is_asked_again(tmp_path):
    fake = FakeSearchApi({TAVILY_URL: lambda body: (200, {"results": []})})
    api = PaidApi("x", tmp_path, max_requests=5, transport=fake, min_interval=0)
    api.post(TAVILY_URL, {"query": "a"}, {})
    [cache_file] = (tmp_path / "x").glob("*.json")
    cache_file.write_text('{"results": [')  # an interrupted write
    assert api.post(TAVILY_URL, {"query": "a"}, {}) == {"results": []}
    assert len(fake.calls) == 2
    assert not list((tmp_path / "x").glob("*.partial"))


def test_an_expired_page_token_ends_one_search_not_the_source(tmp_path):
    def answer(body):
        if body.get("pageToken"):
            return 400, '{"error": {"status": "INVALID_ARGUMENT"}}'
        return 200, {"places": [place("A Shop", "https://ashop.com")], "nextPageToken": "old"}

    fake = FakeSearchApi({PLACES_URL: answer})
    cfg = config(tmp_path, google_places={"queries": ["a", "b"], "max_pages": 2})
    source = PlacesSource(cfg, GOOGLE_KEY, PaidApi("p", tmp_path, 10, fake, min_interval=0))
    source.run()
    assert len(source.found) == 2, "both searches ran"
    assert len(source.notes) == 2


def test_a_refused_first_page_stops_places(tmp_path):
    fake = FakeSearchApi({PLACES_URL: lambda body: (400, '{"error": "API key not valid"}')})
    cfg = config(tmp_path, google_places={"queries": ["a", "b"]})
    source = PlacesSource(cfg, GOOGLE_KEY, PaidApi("p", tmp_path, 10, fake, min_interval=0))
    with pytest.raises(ApiError):
        source.run()
    assert len(fake.calls) == 1


def test_agent_country_and_state_names_are_normalised(tmp_path):
    answer = json.dumps(
        [
            {"name": "A", "city": "Austin", "state": "Texas", "country": "United States"},
            {"name": "B", "city": "Toronto", "state": "Ontario", "country": "Canada"},
            {"name": "C", "city": "Denver", "state": "CO", "country": ""},
        ]
    )
    cfg = agent_config(tmp_path)
    completion = functools.partial(litellm.completion, mock_response=answer)
    agent = AgentSource(cfg, keys(gemini="gm-key-123456"), tmp_path / "cache", completion)
    agent.run()
    assert [(c.state, c.country) for c in agent.found] == [("TX", "US"), ("ON", "CA"), ("CO", "US")]
    assert len(merge(agent.found, ["US", "CA"], [])) == 3, "none dropped as foreign"


def test_a_bracket_before_the_list_and_a_cut_off_list_are_read():
    stores = stores_in_text('Sources [1], [2]:\n[{"name": "A"}, {"name": "B"}]')
    assert [s.name for s in stores or []] == ["A", "B"]
    cut = stores_in_text('[{"name": "A"}, {"name": "B"}, {"name": "C", "webs')
    assert [s.name for s in cut or []] == ["A", "B"]
    assert stores_in_text("[]") == []


def test_an_empty_agent_answer_is_not_cached(tmp_path):
    seen = []

    def completion(**kwargs):
        seen.append(1)
        return litellm.completion(mock_response="[]", **kwargs)

    cfg = agent_config(tmp_path)
    for _ in range(2):
        AgentSource(cfg, keys(gemini="gm-key-123456"), tmp_path / "cache", completion).run()
    assert len(seen) == 2


def test_merging_keeps_the_maps_name_when_records_join():
    web = Candidate(name="Sweaters - Shop Now", source="web_search", website="https://ashop.com")
    maps = Candidate(name="A Shop", source="google_places", city="Boulder", state="CO")
    link = Candidate(
        name="A Shop", source="ai_agent", website="https://ashop.com", city="Boulder", state="CO"
    )
    [store] = merge([web, maps, link], ["US"], [])
    assert store.name == "A Shop"


def test_stores_given_one_website_by_the_lookup_become_one_row():
    maps = Candidate(
        name="A Shop",
        source="google_places",
        website="https://ashop.com",
        city="Boulder",
        state="CO",
    )
    agent = Candidate(name="A Shop", source="ai_agent", city="Boulder")
    stores = merge([maps, agent], ["US"], [])
    assert len(stores) == 2, "no state on the agent's sighting: not matched yet"
    lone = next(s for s in stores if not s.website)
    lone.website, lone.website_source = "https://www.ashop.com", "lookup"
    [store] = fold_by_website(stores)
    assert (store.website, store.website_source) == ("https://ashop.com", "source")
    assert store.sources == ["google_places", "ai_agent"]
    assert store.store_id == "ashop.com"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://cedar.ueniweb.com", "cedar.ueniweb.com"),
        ("https://cedar.mystrikingly.com", "cedar.mystrikingly.com"),
        ("https://cedar.ecwid.com", "cedar.ecwid.com"),
        ("https://cedar.shopsettings.com", "cedar.shopsettings.com"),
        ("https://shop.app/m/cedar", ""),
    ],
)
def test_stores_on_shared_hosts_stay_apart(url, expected):
    assert store_website(url) == expected


# --- the interface's discovery: regions, targets ------------------------------------


def test_a_region_request_becomes_a_capped_discovery():
    from scrapebot.discover.regions import discover_config

    cfg = discover_config(
        50, "europe", ["knitwear", "other"], ["ponchos"], "openai/gpt-5-search-api"
    )
    assert "FR" in cfg.countries
    assert "Paris, France" in cfg.locations
    assert cfg.target_stores == 50
    assert cfg.ai_agent.max_runs == 8
    assert cfg.ai_agent.budget_usd == 0.96
    assert cfg.google_places.queries[:2] == ["sweater boutique", "knitwear store"]
    assert "ponchos boutique" in cfg.google_places.queries
    assert "sweaters and knitwear, ponchos" in cfg.web_search.queries[0]
    assert "Europe" in cfg.web_search.queries[0]


def test_the_agent_keeps_asking_for_new_stores_until_the_target(tmp_path):
    answers = iter(
        [
            json.dumps([{"name": f"S{i}", "website": f"https://s{i}.com"} for i in range(3)]),
            json.dumps([{"name": f"S{i}", "website": f"https://s{i}.com"} for i in range(3, 6)]),
            json.dumps([{"name": "S9", "website": "https://s9.com"}]),
        ]
    )
    prompts = []

    def completion(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        return litellm.completion(mock_response=next(answers), **kwargs)

    cfg = config(
        tmp_path,
        target_stores=5,
        ai_agent={"model": "gemini/gemini-2.5-flash", "areas": ["Colorado"], "max_runs": 10},
    )
    agent = AgentSource(cfg, keys(gemini="gm-key-123456"), tmp_path / "cache", completion)
    seen = []
    agent.run(seen.append)
    assert agent.stores_found() == 6
    assert len(prompts) == 2, "stops once the target is reached"
    assert "already known; find others: S0; S1; S2" in prompts[1]
    assert seen == [3, 6]


def test_the_agent_stops_when_a_round_finds_nothing_new(tmp_path):
    same = json.dumps([{"name": "S0", "website": "https://s0.com"}])
    completion = functools.partial(litellm.completion, mock_response=same)
    cfg = config(
        tmp_path,
        target_stores=50,
        ai_agent={"model": "gemini/gemini-2.5-flash", "areas": ["A", "B"], "max_runs": 20},
    )
    agent = AgentSource(cfg, keys(gemini="gm-key-123456"), tmp_path / "cache", completion)
    agent.run()
    assert (len(agent.calls), agent.cached) == (3, 1), "two rounds of two areas, then stop"


def test_stores_to_visit_prefer_websites_and_agreement():
    from scrapebot.discover.run import stores_to_visit

    a = FoundStore(name="A", website="https://a.com", sources=["ai_agent"])
    b = FoundStore(name="B", website="https://b.com", sources=["ai_agent", "google_places"])
    c = FoundStore(name="C", sources=["social_search"])
    assert [s.name for s in stores_to_visit([a, b, c], 1)] == ["B"]
    assert [s.name for s in stores_to_visit([a, b, c], None)] == ["B", "A"]
