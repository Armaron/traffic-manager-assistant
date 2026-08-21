import { digestPath, inboxPath, navigate, type AppPage } from "../utils/routing";

type AppNavProps = {
  page: AppPage;
};

export function AppNav({ page }: AppNavProps) {
  return (
    <nav className="app-nav" aria-label="Разделы">
      <button
        type="button"
        className={page === "inbox" ? "is-active" : ""}
        onClick={() => navigate(inboxPath())}
      >
        Inbox
      </button>
      <button
        type="button"
        className={page === "digest" ? "is-active" : ""}
        onClick={() => navigate(digestPath())}
      >
        Сводка
      </button>
    </nav>
  );
}
