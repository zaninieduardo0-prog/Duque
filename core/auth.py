from __future__ import annotations

import os
from functools import wraps
from flask import request, jsonify
import os
import typing

try:
	import jwt as _jwt
except Exception:
	_jwt = None


def _load_token() -> str | None:
	# Prioritize explicit env var, then file
	token = os.getenv("DUQUE_API_TOKEN")
	if token:
		return token
	path = os.getenv("DUQUE_API_TOKEN_FILE")
	if path:
		try:
			with open(path, "r", encoding="utf-8") as fh:
				return fh.read().strip()
		except Exception:
			return None
	return None


def _get_provided_token() -> str | None:
	auth = request.headers.get("Authorization") or ""
	if auth.startswith("Bearer "):
		return auth.split(" ", 1)[1].strip()
	# fallback to query param
	provided = request.args.get("token") or request.form.get("token")
	if provided:
		return provided
	return None


def check_api_token() -> bool:
	"""Returns True if token not configured or provided token matches."""
	# If JWT secret is configured, prefer JWT validation
	jwt_secret = os.getenv("DUQUE_JWT_SECRET")
	provided = _get_provided_token()
	if jwt_secret and _jwt is not None and provided:
		try:
			# allow HS256
			_jwt.decode(provided, jwt_secret, algorithms=["HS256"])
			return True
		except Exception:
			return False

	token = _load_token()
	if not token:
		# no token configured -> allow by default (local dev convenience)
		return True
	if not provided:
		return False
	return provided == token


def require_auth(func):
	"""Flask view decorator: returns 401 JSON on missing/invalid token."""

	@wraps(func)
	def wrapper(*args, **kwargs):
		if not check_api_token():
			return jsonify({"ok": False, "erro": "Unauthorized"}), 401
		return func(*args, **kwargs)

	return wrapper
