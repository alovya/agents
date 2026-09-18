export type GraphImportProps = {
  source: string
  errorMessage: string | null
  readOnly?: boolean
  onSourceChange(source: string): void
  onLoadText(): void
  onChooseFile(file: File): void
}

export function GraphImport({
  source,
  errorMessage,
  readOnly = false,
  onSourceChange,
  onLoadText,
  onChooseFile,
}: GraphImportProps) {
  return (
    <section className="graph-import" aria-label="Load graph document">
      <div className="graph-import__source">
        <label htmlFor="graph-json-source">Behavioural graph JSON</label>
        <textarea
          id="graph-json-source"
          value={source}
          readOnly={readOnly}
          onChange={(event) => onSourceChange(event.target.value)}
          rows={8}
        />
      </div>
      <div className="graph-import__actions">
        <button type="button" onClick={onLoadText}>
          Load JSON
        </button>
        <input
          id="graph-json-file"
          className="graph-import__file-input"
          type="file"
          accept="application/json,.json"
          onChange={(event) => {
            const file = event.currentTarget.files?.[0]
            if (file) onChooseFile(file)
          }}
        />
        <label
          className="graph-import__file-button"
          htmlFor="graph-json-file"
        >
          Choose JSON file
        </label>
      </div>
      <p className="graph-import__status" role="status" aria-live="polite">
        {errorMessage}
      </p>
    </section>
  )
}
