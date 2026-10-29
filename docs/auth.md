# Authentication and access control

Identity is Keycloak (realm `clinic`, config in `keycloak/realm-clinic.json`). The API trusts a
token only if it is an RS256 **access** token (`typ` = `Bearer`) from the configured issuer, for the
audience `clinic-api`, signed by a key in the realm's JWKS. Otherwise it answers 401; if the
identity provider cannot be reached and the key is not cached it answers 503, not 401.

## Roles (least privilege, one base role per account)

| Role | Can |
|---|---|
| `patient` | Their own appointments only |
| `doctor` | Appointments on their own schedule only (linked to a doctor record by the seed or import tool) |
| `admin` | Nothing by default. Acts only through explicit permission roles |

| Admin permission | Allows |
|---|---|
| `book_for_patient` | Book on behalf of a patient |
| `manage_any` | Cancel or reschedule any appointment |
| `view_any` | View any appointment or list |

- A token with no base role, or with more than one, is refused (403). Give a person a separate
  account per role.
- Permission roles count only for an admin: a patient holding `manage_any` gains nothing.
- Route guards check role and permission; ownership (own appointment, own schedule) is checked
  again in the service layer.
- Every denial is written to the audit log with the actor's opaque id and a reason code, never a
  name, email, phone, token or free text.

## Demo users (synthetic, demo deployment only)

| Username | Password | Role and permissions |
|---|---|---|
| `patient1`, `patient2` | `demo-<username>` | patient |
| `doctor1` | `demo-doctor1` | doctor, linked to seed doctor `DOC-001` |
| `doctor2` | `demo-doctor2` | doctor, linked to seed doctor `DOC-002` |
| `admin_full` | `demo-admin_full` | admin + all three permissions |
| `admin_view_only` | `demo-admin_view_only` | admin + `view_any` only |

## Getting a token

Swagger UI at `/docs`: Authorize, sign in. Authorization Code with PKCE through the public client
`clinic-docs`. The password grant is disabled for every client, including Keycloak's built-in
`admin-cli`. Postman uses `clinic-postman`, also Authorization Code with PKCE.

## Revocation

Disabling a Keycloak user stops new tokens immediately; existing access tokens remain valid until
they expire (5 minutes). Sessions idle out after 15 minutes and end after 8 hours.

## Before real patients (production hardening, run once per environment)

Keycloak admin commands run inside the container:
`docker compose exec keycloak /opt/keycloak/bin/kcadm.sh ...` after
`kcadm.sh config credentials --server http://localhost:8080 --realm master --user <admin> ...`.

1. Replace the bootstrap admin (`admin`/`admin`) with a named admin and a strong password.
2. Disable the demo users:

for u in patient1 patient2 doctor1 doctor2 admin_full admin_view_only; do
id=$(kcadm.sh get users -r clinic -q username=$u --fields id --format csv --noquotes)
kcadm.sh update users/$id -r clinic -s enabled=false
done

3. Create real staff accounts, one base role each; grant admin permissions deliberately.
4. Require a second factor for doctors and admins: for each such user
   `kcadm.sh update users/<id> -r clinic -s 'requiredActions=["CONFIGURE_TOTP"]'`. Next
   improvement: a role-conditioned OTP step in the browser flow, kept in the realm JSON.
5. Set `KC_HOSTNAME` to the public URL and the proxy-headers option behind Caddy, then decode a
   real token and confirm `iss`, `aud` and `typ` before announcing go-live.
6. Add the production redirect URIs to `clinic-docs` (exact URLs, no wildcards), or remove
   `clinic-docs` and set `DOCS_ENABLED=false` if the clinic should not expose Swagger UI.
7. Confirm events are on (`kcadm.sh get events/config -r clinic`) and decide who reviews them.
