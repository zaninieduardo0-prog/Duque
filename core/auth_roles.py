from __future__ import annotations

from functools import wraps
from flask import request, jsonify
import os

try:
	import jwt
except Exception:
	jwt = None


def _get_provided_token() -> str | None:
	auth = request.headers.get("Authorization") or ""
	if auth.startswith("Bearer "):
		return auth.split(" ", 1)[1].strip()
	return None


def require_role(role: str):
	"""Decorator that requires JWT with 'roles' claim containing specified role.
	If DUQUE_JWT_SECRET is not set or PyJWT not available, denies access.
	"""

	def decorator(func):
		@wraps(func)
		def wrapper(*args, **kwargs):
			secret = os.getenv("DUQUE_JWT_SECRET")
			if not secret or jwt is None:
				return jsonify({"ok": False, "erro": "Role-based auth not configured"}), 403
			token = _get_provided_token()
			if not token:
				return jsonify({"ok": False, "erro": "Missing token"}), 401
			try:
				payload = jwt.decode(token, secret, algorithms=["HS256"])
			except Exception:
				return jsonify({"ok": False, "erro": "Invalid token"}), 401
			roles = payload.get("roles") or []
			if isinstance(roles, str):
				roles = [roles]
			if role not in roles:
				return jsonify({"ok": False, "erro": "Insufficient role"}), 403
			return func(*args, **kwargs)

		return wrapper

	return decorator
