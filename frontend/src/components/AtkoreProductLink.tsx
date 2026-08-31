import type { MouseEvent } from "react";
import { IconExternalLink } from "./Icons";

const POPUP_FEATURES = "width=1000,height=800,noopener";

export function AtkoreProductLink({ url }: { url: string | null }) {
  if (!url) {
    return null;
  }

  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    if (!url || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    event.preventDefault();
    window.open(url, "atkoreProduct", POPUP_FEATURES);
  }

  return (
    <a
      className="atkore-link"
      href={url ?? undefined}
      onClick={handleClick}
      title="View on atkore.com"
      aria-label="View on atkore.com"
    >
      <IconExternalLink size={13} />
    </a>
  );
}
