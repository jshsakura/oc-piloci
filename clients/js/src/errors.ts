/**
 * Base error class for all piLoci SDK errors.
 */
export class PilociError extends Error {
  public readonly status: number | undefined;
  public readonly raw: unknown;

  constructor(message: string, status?: number, raw?: unknown) {
    super(message);
    this.name = "PilociError";
    this.status = status;
    this.raw = raw;
    // Restore prototype chain (required for extends Error in TS targeting ES5/2015)
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Thrown on HTTP 401 — token is missing, expired, or invalid.
 */
export class PilociAuthError extends PilociError {
  constructor(message = "Unauthorized — check your token", raw?: unknown) {
    super(message, 401, raw);
    this.name = "PilociAuthError";
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Thrown on HTTP 403 — valid token but no access to the requested project.
 * Project-scoped endpoints (memory, recall, recommend, contradict) require
 * a JWT that carries `project_id`. Generate one in /settings → Tokens.
 */
export class PilociPermissionError extends PilociError {
  constructor(
    message = "Forbidden — use a project-scoped token for memory/recall/recommend/contradict",
    raw?: unknown
  ) {
    super(message, 403, raw);
    this.name = "PilociPermissionError";
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Thrown on HTTP 422 — request body failed server-side validation.
 * `details` contains the raw Pydantic error list from the server.
 */
export class PilociValidationError extends PilociError {
  public readonly details: unknown;

  constructor(message = "Validation error", details?: unknown, raw?: unknown) {
    super(message, 422, raw);
    this.name = "PilociValidationError";
    this.details = details;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Thrown on HTTP 5xx — server-side failure.
 */
export class PilociServerError extends PilociError {
  constructor(message: string, status: number, raw?: unknown) {
    super(message, status, raw);
    this.name = "PilociServerError";
    Object.setPrototypeOf(this, new.target.prototype);
  }
}
