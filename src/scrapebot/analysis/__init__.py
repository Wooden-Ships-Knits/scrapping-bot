"""Wholesale analysis: what the scraped data says about each store, for deciding who is a
retail partner, a B2B partner or a competitor (PRD 3, the analysis phase; ADR 0011).

Reads a finished run and the operator's own files (stockists, accounts, brands, price
points); never fetches a store and never changes the run's raw tables. Every judgement is
a column beside the evidence, with its reasons.
"""
