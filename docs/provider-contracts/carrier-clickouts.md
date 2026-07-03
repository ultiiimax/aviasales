# Carrier Clickout Contract Notes

Last verified: 2026-06-29

## Scope

Carrier clickouts are manual confirmation links to official airline websites. They are not Flight
Hunter price providers, not live APIs and not browser-observation sources.

Current default carriers:

- Aeroflot: `https://www.aeroflot.ru/`
- Pobeda: `https://www.pobeda.aero/`
- S7 Airlines: `https://www.s7.ru/`
- Ural Airlines: `https://www.uralairlines.ru/`
- Nordwind: `https://nordwindairlines.ru/`
- Red Wings: `https://flyredwings.com/`
- Smartavia: `https://flysmartavia.com/`
- Azimuth: `https://azimuth.aero/`
- Utair: `https://www.utair.ru/`
- Rossiya Airlines: `https://www.rossiya-airlines.com/`
- Turkish Airlines: `https://www.turkishairlines.com/`
- Air Serbia: `https://www.airserbia.com/`
- Pegasus: `https://www.flypgs.com/`
- Uzbekistan Airways: `https://www.uzairways.com/`
- Emirates: `https://www.emirates.com/`
- Qatar Airways: `https://www.qatarairways.com/`
- Etihad: `https://www.etihad.com/`
- flydubai: `https://www.flydubai.com/`

## Contract Rules

- Use HTTPS base URLs only and validate hosts against each source spec.
- Do not claim a carrier link has a known price.
- Do not prefill passenger mix, baggage, currency or route unless a future carrier-specific contract
  proves a stable official template.
- Do not run background browser observation or scraping against carrier sites.
- Carrier links stay outside priced offer ranking and always require external confirmation.
- No provider secrets, cookies, signed URLs or personal identifiers are put in carrier URLs.
