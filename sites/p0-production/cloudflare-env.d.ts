declare namespace Cloudflare {
  interface Env {
    DB: D1Database;
    ASSETS: Fetcher;
    YANDEX_DIRECT_OAUTH_TOKEN?: string;
    YANDEX_DIRECT_CLIENT_LOGIN?: string;
    YANDEX_DIRECT_CAMPAIGN_ID?: string;
    YANDEX_METRICA_OAUTH_TOKEN?: string;
    YANDEX_METRICA_COUNTER_ID?: string;
    YANDEX_METRICA_GOAL_ID?: string;
    P0_E2E_FIXTURE_SCENARIO?: string;
  }
}
