import { useEffect, useState } from "react";

import { DigestPage } from "./pages/DigestPage";
import { InboxPage } from "./pages/InboxPage";
import { parseLocation, type AppLocation } from "./utils/routing";

export default function App() {
  const [location, setLocation] = useState<AppLocation>(() => parseLocation());

  useEffect(() => {
    function onPop() {
      setLocation(parseLocation());
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const showDigest = location.page === "digest";

  // Keep Inbox mounted while Сводка is open. Unmounting it forced a full boot
  // (health + all chats + messages) and looked like a resync.
  return (
    <>
      <div className="app-pane" hidden={showDigest}>
        <InboxPage
          active={!showDigest}
          initialChatId={location.chatId}
          initialMessageId={location.messageId}
        />
      </div>
      {showDigest ? <DigestPage /> : null}
    </>
  );
}
