import { useEffect, useState } from "react";
import { TOAST_EVENT as EVENT } from "./toastBus";

export function ToastHost() {
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const on = (e: Event) => {
      setMsg((e as CustomEvent<string>).detail);
      clearTimeout(timer);
      timer = setTimeout(() => setMsg(null), 3500);
    };
    window.addEventListener(EVENT, on);
    return () => {
      window.removeEventListener(EVENT, on);
      clearTimeout(timer);
    };
  }, []);
  return (
    <div className="toast-host" aria-live="polite" role="status">
      {msg ? <div className="toast">{msg}</div> : null}
    </div>
  );
}
