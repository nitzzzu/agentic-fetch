Feature: Service health
  Operators and skills probe /health to confirm the service is up and see
  which fetch plugins were discovered.

  Scenario: Health reports status and discovered plugins
    When I request the service health
    Then the service reports status "ok"
    And the discovered plugins include "reddit", "github" and "wikipedia"
