"use client";

import { useEffect, useRef } from "react";

const GSI_SRC = "https://accounts.google.com/gsi/client";

interface GoogleId {
  initialize(options: { client_id: string; callback: (r: { credential: string }) => void }): void;
  renderButton(element: HTMLElement, options: Record<string, string>): void;
}
type GoogleWindow = Window & { google?: { accounts: { id: GoogleId } } };

/** "Sign in with Google". Renders nothing until a Google client id is configured. */
export function GoogleButton({
  onCredential,
  clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID,
}: {
  onCredential: (idToken: string) => void;
  clientId?: string;
}) {
  if (!clientId) return null;
  return <Loaded clientId={clientId} onCredential={onCredential} />;
}

function Loaded({ clientId, onCredential }: { clientId: string; onCredential: (idToken: string) => void }) {
  const holder = useRef<HTMLDivElement>(null);
  const callback = useRef(onCredential);
  useEffect(() => {
    callback.current = onCredential;
  });

  useEffect(() => {
    const init = () => {
      const id = (window as GoogleWindow).google?.accounts.id;
      if (!id || !holder.current) return;
      id.initialize({ client_id: clientId, callback: (r) => callback.current(r.credential) });
      id.renderButton(holder.current, { theme: "outline", size: "large", width: "280" });
    };
    if ((window as GoogleWindow).google) return init();
    const script = document.createElement("script");
    script.src = GSI_SRC;
    script.async = true;
    script.onload = init;
    document.head.appendChild(script);
  }, [clientId]);

  return <div ref={holder} className="flex justify-center" />;
}
