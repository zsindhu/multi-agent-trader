import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('React error boundary caught:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-6 bg-red-500/10 border border-red-500/20 rounded-xl m-4">
          <h3 className="text-red-400 font-semibold mb-2">Something went wrong on this page</h3>
          <p className="text-sm text-slate-400 mb-3">
            This page encountered an error. The rest of the app still works — try refreshing or switching to another page.
          </p>
          <pre className="text-xs text-red-300 bg-[#0a0f1e] p-3 rounded overflow-auto max-h-40 mb-3">
            {this.state.error?.toString()}
          </pre>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-4 py-1.5 bg-[#334155] text-white text-sm rounded hover:bg-[#475569] transition-colors"
          >
            Try Again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
