# Export contract C1

The existing export_csv(rows) returns all rows as an in-memory CSV string using
the standard csv.writer formatting. Preserve full export and its CSV formatting.
Do not persist user data. There is no preview API yet.
