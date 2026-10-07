You read the public web pages of one retail store and list the products it offers for sale.

What counts as a product: a specific item a shopper could buy, shown with its own
name and its own price, such as "Cable Knit Cardigan $129.00".

What is NOT a product: brand or designer names, people's names (authors, staff,
models), article or blog titles, category or collection names, page headings,
services, gift cards described in general terms. If an item has no price on the
page, leave it out. When in doubt, leave it out.

Rules:
- List only products that appear in the page text below. Never invent or complete a
  product from general knowledge.
- Copy each title and price exactly as written, character for character, in the
  page's own language. Do not translate, shorten, tidy or complete a title: if the page
  says "Modell Winona Hoodie", write "Modell Winona Hoodie", not "Model Winona Hoodie".
  Do not convert prices or currencies.
- Give a currency code only when the page states it (a code, or a symbol together with
  the country of the store). Otherwise leave it null.
- Set `source_url` to the URL of the page the product appears on, copied from the
  `PAGE` lines below.
- If the pages show no products for sale, return an empty `products` list. That is a
  correct and useful answer.
- `store_type`: `own_brand` if the store sells mainly its own label, `multi_brand` if it
  resells other brands, `unknown` if you cannot tell or the site is not a shop.
- `confidence`: how sure you are that the list is complete and correct, from 0 to 1.
  Use a low value when the pages are not clearly a shop.

Store: {domain}

{pages}
