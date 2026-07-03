# ADR 0054: Extended Carrier Confirmation Links

Date: 2026-06-29

## Status

Accepted.

## Context

The monster plan expects official airline sites to appear as secondary confirmation links for common
RU-first routes and nearby international routes. The application already had Aeroflot, Pobeda and
S7 as carrier links, but the catalog was narrower than the product plan.

## Decision

- Add official carrier-site confirmation links for Ural Airlines, Nordwind, Red Wings, Smartavia,
  Azimuth, Utair, Rossiya Airlines, Turkish Airlines, Air Serbia, Pegasus, Uzbekistan Airways,
  Emirates, Qatar Airways, Etihad and flydubai.
- Treat every carrier entry as `source_type="carrier"`, `link_strategy="manual"`,
  `browser_observation_allowed=False` and `price_known=False`.
- Use official HTTPS base URLs only. Do not generate precise booking/search deep links unless a
  future source-specific contract proves a safe URL template.
- Enable these carrier links by default through `CARRIER_LINKS_ENABLED` so search bundles can show
  secondary confirmation options.

## Consequences

- Users get broader manual confirmation coverage without Flight Hunter claiming it found a carrier
  fare.
- The source catalog remains conservative: no scraping, no API calls, no background jobs and no
  in-app booking.
- Future work can add per-carrier route availability, localized URL templates or official APIs only
  behind separate contracts and tests.
