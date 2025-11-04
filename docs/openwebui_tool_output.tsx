import React from "react";

type ValidationError = {
  message: string;
};

type ParseResponse = {
  status: string;
  data: Record<string, unknown>;
  metadata: {
    validation?: {
      status?: string;
      errors?: ValidationError[];
    };
    timings?: Record<string, number | boolean>;
    [key: string]: unknown;
  };
};

type HolidayParseResultProps = {
  result: ParseResponse | null;
};

const formatJson = (payload: Record<string, unknown>) =>
  JSON.stringify(payload, null, 2);

export const HolidayParseResult: React.FC<HolidayParseResultProps> = ({ result }) => {
  if (!result) {
    return <div className="text-muted">No holiday search has been run yet.</div>;
  }

  const validation = result.metadata?.validation;
  const errors = validation?.errors ?? [];
  const failed = result.status?.toLowerCase() === "failed";

  return (
    <div className="holiday-parse-result">
      <header className="d-flex align-items-center gap-2">
        <h3 className="m-0">Holiday Search</h3>
        <span className={`badge ${failed ? "bg-danger" : "bg-success"}`}>{result.status}</span>
        {validation?.status && (
          <span className="badge bg-secondary">Validation: {validation.status}</span>
        )}
      </header>

      {failed && errors.length > 0 && (
        <div className="alert alert-danger mt-3" role="alert">
          <h4 className="alert-heading">Validation errors</h4>
          <ul>
            {errors.map((error, index) => (
              <li key={`${error.message}-${index}`}>{error.message}</li>
            ))}
          </ul>
        </div>
      )}

      <section className="mt-3">
        <h4>Structured data</h4>
        <pre className="bg-dark text-white p-3 rounded small overflow-auto">
          {formatJson(result.data)}
        </pre>
      </section>

      <section className="mt-3">
        <h4>Metadata</h4>
        <pre className="bg-dark text-white p-3 rounded small overflow-auto">
          {formatJson(result.metadata as Record<string, unknown>)}
        </pre>
      </section>
    </div>
  );
};

export default HolidayParseResult;
