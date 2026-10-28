# Privacy and compliance: engineering summary

**This is an engineering summary, not legal advice.** It rests on two secondary sources (listed at
the end), not on the statutes. Verify against the current Data Protection Act, 2019, the Digital
Health Act, 2023 and its regulations, and take counsel before go-live.

## What the system does about it

| Principle | In this system |
|---|---|
| Health data is sensitive personal data | Name, email, phone and cancellation reasons are never logged and never returned outside the owner's own `/me` and the minimal appointment view |
| Need-to-know access | One base role per account; admins hold explicit permission roles; patients and doctors see only their own records |
| Security safeguards | TLS in production, short-lived tokens, brute-force lockout, password policy, encrypted backups, non-root containers |
| Accountability | Audit log of authorization denials and profile provisioning; Keycloak records login events for 90 days |
| Data minimisation | A patient record is created from the token's name and email only; no phone, no date of birth, no clinical data |
| Erasure | Anonymise the patient row and keep appointment shells (see the open item on retention) |

## Open items the clinic must decide (not code)

1. **Retention versus erasure.** One source states the Digital Health Act requires controllers to
   keep health data for at least 20 years. That sits against a patient's erasure request. We
   anonymise rather than delete, but the retention period and who may order erasure need a
   decision recorded in the assumptions log.
2. **Where the data lives.** The Digital Health Act and the ODPC guidance appear to differ on
   transfers abroad. Record where the OpenStack host and the backup bucket are physically, and the
   legal basis for any storage outside Kenya.
3. **ODPC registration.** Patient care and health administration are not exempt from registration
   regardless of size. The clinic registers as controller; confirm whether this vendor is a
   processor and put a written processor contract in place.
4. **Data protection impact assessment.** Processing sensitive data is listed as needing one.
5. **Consent and lawful basis.** Explicit consent is named for health data. The API does not
   capture consent; the patient onboarding process must.
6. **Breach procedure.** ODPC notice within 72 hours of awareness. One source also describes a
   48-hour notice to the Digital Health Agency. Write one incident document naming who decides,
   who is told and what is preserved, and rehearse it.
7. **Records of processing and a retention schedule.** Required documents, owned by the clinic.
8. **Interoperability and certification.** The Digital Health Agency's national systems and
   certification scheme may impose coding standards and security measures such as multi-factor
   authentication. See `docs/integration-notes.md` for the FHIR mapping.

## Sources

- ODPC, Data Controllers 360 Degrees Compliance Requirements (Z card)
- Clyde & Co, health data protection in Kenya (March 2026)
