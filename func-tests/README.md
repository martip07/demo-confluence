
# Test data

The database dump and `confluence.cfg.xml.tmpl` are dumped from a 7.11.6
instance.

## Updating the test data

Periodically Confluence will move forward far enough that it is unable to
upgrade databases from older unsupported versions. In this case you will need to
upgrade the database to the oldest supported version and re-dump the DB. Steps
to do this are:

* Generate a local Confluence image of the oldest supported version (see
  [Atlassian Support End of Life Policy](https://confluence.atlassian.com/support/atlassian-support-end-of-life-policy-201851003.html).
* Run the func-tests up to the start of the smoke-tests (these won't start by
  default if `CONFLUENCE_ADMIN_PWD` is not set.
* Stop the func-tests after the DB upgrade has run, then start the Postgres
  instance (`docker-compose up postgres`).
* `exec` into the running postgres container and dump the DB with `pg_dump -U confluence confuence > confluence.sql`
* Copy the dump to `func-tests/postgres` and update the Dockerfile, scripts,
  etc.

You may find that Confluence will fail to start with a `500` error after; this
may be due to an incompatible version in
`func-tests/confluence/confluence-home/confluence.cfg.xml.tmpl`. You can
retrieve the correct version from the error-message in the startup logs on the
image and update the file.
