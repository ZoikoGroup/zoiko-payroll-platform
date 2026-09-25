import { Component } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

// Catches render errors thrown by a page so one broken page shows an inline
// error card instead of unmounting the whole app to a blank white screen.
// `resetKey` (the current pathname) clears the error when the user navigates
// away, so the shell's sidebar stays a working way out.
export default class PageErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Page render error:", error, info?.componentStack);
  }

  componentDidUpdate(prevProps) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div role="alert" className="mx-auto max-w-xl rounded-xl border border-error/30 bg-error-light p-6">
        <div className="flex items-center gap-2 text-error">
          <AlertTriangle size={18} />
          <h2 className="text-sm font-bold">This page failed to load</h2>
        </div>
        <p className="mt-2 text-sm text-foreground-secondary">
          Something went wrong while rendering this page. The rest of the app is unaffected — you can retry or
          use the sidebar to go elsewhere.
        </p>
        {error?.message && (
          <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-surface px-3 py-2 text-xs text-foreground-muted">
            {error.message}
          </pre>
        )}
        <button
          type="button"
          onClick={() => this.setState({ error: null })}
          className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-sm font-medium text-white hover:bg-primary-hover"
        >
          <RotateCcw size={14} /> Try again
        </button>
      </div>
    );
  }
}
