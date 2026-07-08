import "@/App.css";
import Workbook from "@/components/Workbook";
import ErrorBoundary from "@/components/ErrorBoundary";

function App() {
  return (
    <div className="App">
      <ErrorBoundary>
        <Workbook />
      </ErrorBoundary>
    </div>
  );
}

export default App;
