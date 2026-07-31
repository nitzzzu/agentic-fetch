Feature: Fetch pipeline
  Fetching a URL returns the page converted to markdown. Static pages are
  served by the plain-HTTP tier, results are cached for the configured TTL,
  and long documents paginate with a continuation offset.

  Scenario: A static HTML article is converted to markdown by the HTTP tier
    Given the network serves a static HTML article at "https://site.test/article"
    When I fetch "https://site.test/article"
    Then the fetch succeeds with method "httpx"
    And the markdown contains the article heading "Offline Testing"

  Scenario: A repeat fetch within the TTL is served from the cache
    Given the network serves a static HTML article at "https://site.test/article"
    And "https://site.test/article" has already been fetched once
    When I fetch "https://site.test/article"
    Then the response is marked as cached

  Scenario: Long documents paginate with a continuation offset
    Given the network serves a static HTML article at "https://site.test/article"
    When I fetch "https://site.test/article" with a budget of 50 tokens
    Then the response is truncated and reports a positive next offset

  Scenario: Non-http URLs are rejected up front
    When I fetch "ftp://site.test/article"
    Then the request fails with status 422

  Scenario: Batch fetch isolates per-URL failures
    Given a fetch engine where "https://ok.test/" succeeds and "https://boom.test/" raises an error
    When I batch-fetch "https://ok.test/" and "https://boom.test/"
    Then the batch reports 1 success and 1 failure
    And the failed entry names "https://boom.test/" with an error message
