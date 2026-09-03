-- "Wrong, expected X" from the questions page. Together with feedback this is
-- the seed of the eval set.
ALTER TABLE query_log ADD COLUMN feedback_note TEXT;
