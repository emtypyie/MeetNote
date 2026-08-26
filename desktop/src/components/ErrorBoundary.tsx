import { Component, type ErrorInfo, type ReactNode } from "react";
import { RotateCw } from "lucide-react";
import { Button } from "./ui";

interface Props {
  children: ReactNode;
  /** Called when the user asks to try again — clear whatever local state
   * caused the crash before remounting the subtree. */
  onRetry?: () => void;
  /** Optional extra recovery action, e.g. "Back to Meetings". */
  secondaryAction?: { label: string; onClick: () => void };
  title?: string;
}

interface State {
  error: Error | null;
}

/**
 * Last line of defense so a runtime error in any page never produces a
 * silently blank window (product spec: "A black/blank meeting window is
 * not an acceptable state"). React unmounts the whole tree on an uncaught
 * render error unless something below the crash point catches it — this
 * is that something, kept close to the root so no page can slip past it.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("Unhandled error in", this.props.title ?? "component", error, info.componentStack);
  }

  private handleRetry = () => {
    this.props.onRetry?.();
    this.setState({ error: null });
  };

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
        <h1 className="text-lg font-semibold text-[var(--color-text)]">
          Something went wrong{this.props.title ? ` while ${this.props.title}` : ""}.
        </h1>
        <p className="max-w-md text-sm text-[var(--color-text-muted)]">
          {this.state.error.message || "An unexpected error occurred."}
        </p>
        <div className="mt-2 flex gap-2">
          <Button variant="primary" onClick={this.handleRetry}>
            <RotateCw size={15} />
            Retry
          </Button>
          {this.props.secondaryAction && (
            <Button variant="secondary" onClick={this.props.secondaryAction.onClick}>
              {this.props.secondaryAction.label}
            </Button>
          )}
        </div>
      </div>
    );
  }
}
