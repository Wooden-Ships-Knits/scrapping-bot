You decide what kind of shop one retail store is, from its own pages and products.

- `multi_brand`: the store resells clothing from several other brands or designers,
  like a boutique, a department store or a multi-brand online shop. A boutique that
  also has a small house label is still `multi_brand`.
- `own_brand`: the store sells mainly its own label, like a brand's own website
  (Nike, a knitwear label, a designer's shop), even if it lists a few collaborations.
- `unknown`: you cannot tell, or the site is not a clothing shop.

How to decide:
- Vendor names that are just the store's own name tell you nothing: boutiques often
  put their own name on every product.
- Words like "brands we carry", "our designers", "shop by brand", or product names
  that start with other brand names point to `multi_brand`.
- "Our collection", "designed in our studio", "made by us" and one brand name on
  everything point to `own_brand`.
- Use only what is written below. Never use general knowledge about the store.
- `brands_carried`: other brands named on the pages or in the product names, as
  written. Leave out the store's own name.
- `confidence`: from 0 to 1. Use a low value when the evidence is thin.
- `reason`: one short sentence naming the evidence.

Store: {domain}

Vendors on its products (name: how many products):
{vendors}

Some product names:
{titles}

{pages}
