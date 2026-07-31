Feature: Cache-backed document workflow
  The service persists fetched or synthesized markdown so agents can
  re-read, search, grep, and line-slice documents without re-fetching.

  Scenario: Filed synthesis content is searchable
    Given an empty cache
    When I file synthesized markdown at "note://project/decisions" saying "We chose FastAPI for the HTTP layer because of pydantic integration"
    Then searching the cache for "FastAPI" returns "note://project/decisions" as the top hit

  Scenario: Cached documents can be read by line range
    Given a cached document at "https://docs.example.test/guide" with 10 numbered lines
    When I request lines 3 to 5 of "https://docs.example.test/guide"
    Then the line response contains lines 3 through 5 and no others

  Scenario: Line reads for an unknown URL fail with 404
    Given an empty cache
    When I request lines 1 to 5 of "https://never-fetched.example.test/"
    Then the request fails with status 404

  Scenario: Grep returns matching lines with their line numbers
    Given a cached document at "https://docs.example.test/guide" with 10 numbered lines
    When I grep "https://docs.example.test/guide" for the pattern "line 7"
    Then the grep result marks line 7 as a match

  Scenario: Grep rejects an invalid regular expression
    Given a cached document at "https://docs.example.test/guide" with 10 numbered lines
    When I grep "https://docs.example.test/guide" for the pattern "[unclosed"
    Then the request fails with status 400

  Scenario: Evicted documents are no longer readable
    Given a cached document at "https://docs.example.test/guide" with 10 numbered lines
    When I evict "https://docs.example.test/guide" from the cache
    And I request lines 1 to 3 of "https://docs.example.test/guide"
    Then the request fails with status 404
