CREATE UNIQUE INDEX estimate_lines_relation_unique
ON estimate_lines (estimate_id, relation_id)
WHERE relation_id IS NOT NULL;
