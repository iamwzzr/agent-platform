export type ApiErrorCode = "http" | "network" | "invalid_response";

const UNKNOWN_ERROR_MESSAGE =
  "Something went wrong while contacting the service. Please try again.";

const DETAIL_MESSAGES: Readonly<Record<string, string>> = {
  "Job not found": "The requested role could not be found.",
  "Document not found": "The requested evidence document could not be found.",
  "Document ingestion conflict":
    "The saved evidence no longer matches its indexed content.",
  "Invalid run request": "The run request is not valid.",
  "Run input not found": "One or more run inputs could not be found.",
  "Run request conflicts with existing state":
    "This run key was already used with different inputs.",
  "Run is already executing": "This run is already being processed.",
  "Run service unavailable":
    "The run service is temporarily unavailable. Please try again.",
  "Run execution failed":
    "The run could not be started. Your saved progress has been kept.",
  "Run not found": "The requested run could not be found.",
  "Run cannot be resumed": "This run can no longer be resumed.",
};

const STATUS_MESSAGES: Readonly<Record<number, string>> = {
  400: "The service could not understand the request.",
  401: "You are not authorized to perform this action.",
  403: "You do not have access to this resource.",
  404: "The requested resource could not be found.",
  408: "The request timed out. Please try again.",
  409: "The request conflicts with the resource's current state.",
  422: "Please check the submitted fields and try again.",
  429: "The service is busy. Please wait before trying again.",
  503: "The service is temporarily unavailable. Please try again.",
};

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number | null;
  readonly retryable: boolean;

  constructor(
    message: string,
    options: {
      code: ApiErrorCode;
      status?: number | null;
      retryable?: boolean;
    },
  ) {
    super(message);
    this.name = "ApiError";
    this.code = options.code;
    this.status = options.status ?? null;
    this.retryable = options.retryable ?? false;
  }
}

export interface RequestJsonOptions extends Omit<RequestInit, "body"> {
  json?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function getKnownDetail(payload: unknown): string | null {
  if (!isRecord(payload) || typeof payload.detail !== "string") {
    return null;
  }

  return DETAIL_MESSAGES[payload.detail] ?? null;
}

function getHttpMessage(status: number, payload: unknown): string {
  const knownDetail = getKnownDetail(payload);
  if (knownDetail !== null) {
    return knownDetail;
  }

  if (status >= 500) {
    return "The service is temporarily unavailable. Please try again.";
  }

  return STATUS_MESSAGES[status] ?? UNKNOWN_ERROR_MESSAGE;
}

function isRetryableStatus(status: number): boolean {
  return status === 408 || status === 429 || status >= 500;
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (isRecord(error) && error.name === "AbortError")
  );
}

export function getErrorMessage(error: unknown): string {
  if (isApiError(error)) {
    return error.message;
  }

  if (isAbortError(error)) {
    return "The request was cancelled.";
  }

  return UNKNOWN_ERROR_MESSAGE;
}

async function readResponseBody(response: Response): Promise<{
  body: unknown;
  parsed: boolean;
}> {
  const text = await response.text();
  if (text.length === 0) {
    return { body: null, parsed: true };
  }

  try {
    return { body: JSON.parse(text) as unknown, parsed: true };
  } catch {
    return { body: null, parsed: false };
  }
}

export async function requestJson<T>(
  path: string,
  options: RequestJsonOptions = {},
): Promise<T> {
  const { json, headers: inputHeaders, ...requestOptions } = options;
  const headers = new Headers(inputHeaders);

  let body: BodyInit | undefined;
  if (json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(json);
  }

  let response: Response;
  try {
    response = await fetch(path, {
      ...requestOptions,
      headers,
      body,
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }

    throw new ApiError(
      "The service could not be reached. Your saved progress has been kept.",
      { code: "network", retryable: true },
    );
  }

  let responseBody: Awaited<ReturnType<typeof readResponseBody>>;
  try {
    responseBody = await readResponseBody(response);
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }

    throw new ApiError(
      "The service response could not be read. Your saved progress has been kept.",
      { code: "network", retryable: true },
    );
  }

  if (!response.ok) {
    throw new ApiError(getHttpMessage(response.status, responseBody.body), {
      code: "http",
      status: response.status,
      retryable: isRetryableStatus(response.status),
    });
  }

  if (!responseBody.parsed || response.status === 204) {
    if (response.status === 204) {
      return undefined as T;
    }

    throw new ApiError(
      "The service returned an unreadable response. Please try again.",
      {
        code: "invalid_response",
        status: response.status,
        retryable: true,
      },
    );
  }

  return responseBody.body as T;
}
