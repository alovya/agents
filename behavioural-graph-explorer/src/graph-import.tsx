export type GraphImportProps = {
  source: string
  errorMessage: string | null
  onSourceChange(source: string): void
  onLoadText(): void
  onChooseFile(file: File): void
}

export function GraphImport({
  source,
  errorMessage,
  onSourceChange,
  onLoadText,
  onChooseFile,
}: GraphImportProps) {
  return (
    <section className="graph-import" aria-label="Load graph document">
      <div className="graph-import__source">
        <label htmlFor="graph-json-source">Graph document JSON</label>
        <textarea
          id="graph-json-source"
          value={source}
          onChange={(event) => onSourceChange(event.target.value)}
          rows={8}
        />
      </div>
      <div className="graph-import__actions">
        <button type="button" onClick={onLoadText}>
          Load JSON
        </button>
        <label htmlFor="graph-json-file">Choose JSON file</label>
        <input
          id="graph-json-file"
          type="file"
          accept="application/json,.json"
          onChange={(event) => {
            const file = event.currentTarget.files?.[0]
            if (file) onChooseFile(file)
          }}
        />
      </div>
      <p className="graph-import__status" role="status" aria-live="polite">
        {errorMessage}
      </p>
    </section>
  )
}
