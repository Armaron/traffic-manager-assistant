type ConnectionState = "checking" | "connected" | "disconnected";

type HealthStatusProps = {
  state: ConnectionState;
  detail?: string;
};

export function HealthStatus({ state, detail }: HealthStatusProps) {
  const label =
    state === "connected"
      ? "Backend connected"
      : state === "checking"
        ? "Checking backend..."
        : "Backend unavailable";

  return (
    <div className={`health-status health-status--${state}`}>
      <span className="health-status__dot" aria-hidden="true" />
      <div>
        <p className="health-status__label">{label}</p>
        {detail ? <p className="health-status__detail">{detail}</p> : null}
      </div>
    </div>
  );
}
