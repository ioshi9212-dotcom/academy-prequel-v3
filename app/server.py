# Academy Prequel V3 / Variant B runtime entrypoint.
# Railway runs `uvicorn app.server:app`; keep this file as the stable shim.
from app.variant_b_runtime import app
