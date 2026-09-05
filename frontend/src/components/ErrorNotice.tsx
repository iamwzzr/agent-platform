import { useEffect, useRef, type ReactNode } from "react";

interface ErrorNoticeProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  onReset?: () => void;
  retryLabel?: string;
  focusOnMount?: boolean;
  children?: ReactNode;
}

export function ErrorNotice({
  title = "Something needs attention",
  message,
  onRetry,
  onReset,
  retryLabel = "Try again",
  focusOnMount = false,
  children,
}: ErrorNoticeProps) {
  const noticeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focusOnMount) {
      noticeRef.current?.focus();
    }
  }, [focusOnMount]);

  return (
    <div
      className="error-notice"
      ref={noticeRef}
      role="alert"
      tabIndex={focusOnMount ? -1 : undefined}
    >
      <span className="error-notice__mark" aria-hidden="true">
        !
      </span>
      <div className="error-notice__body">
        <strong>{title}</strong>
        <p>{message}</p>
        {children ? <div className="error-notice__detail">{children}</div> : null}
        {onRetry || onReset ? (
          <div className="error-notice__actions">
            {onRetry ? (
              <button className="secondary-button" type="button" onClick={onRetry}>
                {retryLabel}
              </button>
            ) : null}
            {onReset ? (
              <button className="text-button" type="button" onClick={onReset}>
                Start over
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
