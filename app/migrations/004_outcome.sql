-- What the bot did with a question: answered, refused, budget, no_provider.
-- Filters and counts keyed on cost IS NULL confused a model refusal (which
-- costs tokens) with a budget stop (which does not).
ALTER TABLE query_log ADD COLUMN outcome TEXT;
UPDATE query_log SET outcome = CASE WHEN cost IS NULL THEN 'refused' ELSE 'answered' END;
