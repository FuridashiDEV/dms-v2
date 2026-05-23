# Deployment Options

## Controlled pilot VM

Recommended for first pilots.

- Django app.
- PostgreSQL.
- Persistent media storage.
- Optional Qdrant.
- Optional local AI/OCR runtime if hardware allows.

## Customer-hosted

Possible after security review and environment agreement.

- Customer provides server, database, storage and backup policy.
- Secrets remain in customer-controlled environment.

## Future scaling path

- Kubernetes-ready templates exist as foundation.
- GPU workers and KEDA-compatible scaling are future scaling options.
- They are not required for first controlled pilot.

## Not included now

- Managed production Kubernetes service operated at scale.
- Dedicated data center.
- Payment gateway infrastructure.
