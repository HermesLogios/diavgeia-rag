\pset pager off

-- Α. Δείγμα: πώς μοιάζει ένα tsvector
SELECT content, content_tsv
FROM chunks
WHERE content ILIKE '%συντηρήσεις σχολικών%'
LIMIT 2;

-- Β. Δουλεύει το stemming; (πρέπει να βγει true)
SELECT to_tsvector('greek', immutable_unaccent('Συντηρήσεις σχολικών κτιρίων'))
       @@ plainto_tsquery('greek', immutable_unaccent('συντήρηση σχολικού κτιρίου'))
       AS stemming_ok;

-- Γ. Αγνοούνται οι τόνοι; (πρέπει να βγει true)
SELECT to_tsvector('greek', immutable_unaccent('ΠΡΟΜΗΘΕΙΑ ΚΑΥΣΙΜΩΝ'))
       @@ plainto_tsquery('greek', immutable_unaccent('προμήθεια καυσίμων'))
       AS accents_ok;

-- Δ. Πρώτη λεξιλογική αναζήτηση με κατάταξη
SELECT ts_rank(content_tsv,
               plainto_tsquery('greek', immutable_unaccent('συντήρηση σχολικών κτιρίων'))) AS rank,
       left(content, 70) AS content
FROM chunks
WHERE content_tsv @@ plainto_tsquery('greek', immutable_unaccent('συντήρηση σχολικών κτιρίων'))
ORDER BY rank DESC
LIMIT 5;