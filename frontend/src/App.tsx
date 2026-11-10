const PLANNED_FEATURES = [
  'Projects as folders',
  'Upload or record audio and get a transcript',
  'Edit, copy and download transcripts (.md / .txt)',
  'Screenshots by file picker or Ctrl+V',
  'Export a project as a ZIP',
]

function App() {
  return (
    <main className="app">
      <header>
        <h1>EchoNotes</h1>
        <p className="tagline">Turn audio into organized text notes.</p>
      </header>
      <section aria-labelledby="coming-soon">
        <h2 id="coming-soon">Coming soon</h2>
        <ul>
          {PLANNED_FEATURES.map((feature) => (
            <li key={feature}>{feature}</li>
          ))}
        </ul>
      </section>
    </main>
  )
}

export default App
