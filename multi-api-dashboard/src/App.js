import React, { useState, useEffect} from 'react';
import { Send, Loader2, TrendingUp, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const API_ENDPOINTS = {
  api1: 'https://allan-hyperspatial-apogamically.ngrok-free.dev/chat',
  api2: 'https://osteitic-rosalina-nonmilitantly.ngrok-free.dev/api/run',  
  api3: 'https://fc983e2035da.ngrok-free.app/'   
};

const MultiAPIQueryApp = () => {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [vegaLoaded, setVegaLoaded] = useState(false);
  const [fullscreenSpec, setFullscreenSpec] = useState(null);
  const [fullscreenTable, setFullscreenTable] = useState(null);

  useEffect(() => {
    const loadVegaLibraries = async () => {
      if (window.vegaEmbed) {
        setVegaLoaded(true);
        return;
      }

      const scripts = [
        'https://cdn.jsdelivr.net/npm/vega@5',
        'https://cdn.jsdelivr.net/npm/vega-lite@5',
        'https://cdn.jsdelivr.net/npm/vega-embed@6'
      ];

      for (const src of scripts) {
        await new Promise((resolve, reject) => {
          const script = document.createElement('script');
          script.src = src;
          script.onload = resolve;
          script.onerror = reject;
          document.head.appendChild(script);
        });
      }
      setVegaLoaded(true);
    };

    loadVegaLibraries();
  }, []);

  useEffect(() => {
    if (!fullscreenSpec || !window.vegaEmbed) return;

    const el = document.getElementById('fullscreen-vega');
    if (!el) return;
    el.innerHTML = '';

    window.vegaEmbed(
      '#fullscreen-vega',
      {
        ...fullscreenSpec,
        width: 'container',
        height: 'container',
        autosize: { type: 'fit', contains: 'padding' }
      },
      {
        actions: false,
        theme: 'dark',
        renderer: 'canvas'
      }
    ).catch(err => console.error('Fullscreen Vega error:', err));
  }, [fullscreenSpec, vegaLoaded]);

  const calculateRelevancy = async (query, answer) => {
    try {
      const res = await fetch('http://localhost:4000/relevancy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, answer })
      });
      const data = await res.json();
      return data.score ?? 0;
    } catch {
      return 0;
    }
  };

  const normalizeApi2 = (raw) => {
    if (!raw) return raw;
    const out = { ...raw };

    if (raw.summary_text) out.summary = raw.summary_text;
    if (!out.summary && raw.raw_output) {
      out.summary = raw.raw_output.summary_text || raw.raw_output.summary || out.summary;
    }

    const buildTableFrom = (s) => {
      if (!s) return null;
      if (s.headers && s.rows) return { headers: s.headers, rows: s.rows };
      if (s.columns && s.sample_rows) {
        const cols = s.columns;
        const sample = s.sample_rows;
        if (Array.isArray(sample) && sample.length > 0) {
          if (Array.isArray(sample[0])) return { headers: cols, rows: sample };
          if (typeof sample[0] === 'object') return { headers: cols, rows: sample.map(r => cols.map(c => r[c])) };
        }
      }
      if (Array.isArray(s)) {
        if (s.length > 0 && Array.isArray(s[0])) return { headers: s[0], rows: s.slice(1) };
        if (s.length > 0 && typeof s[0] === 'object') {
          const headers = Object.keys(s[0]);
          const rows = s.map(r => headers.map(h => r[h]));
          return { headers, rows };
        }
      }
      if (typeof s === 'object' && s.sample_rows) return buildTableFrom(s.sample_rows);
      return null;
    };

    if (!out.table) {
      let tableCandidate = null;
      if (raw.sample_rows) tableCandidate = buildTableFrom(raw.sample_rows);
      if (!tableCandidate && raw.raw_output) tableCandidate = buildTableFrom(raw.raw_output.sample_rows || raw.raw_output);
      if (tableCandidate) out.table = tableCandidate;
    }

    // For api2: if table is a markdown string, use it as summary with markdown output_type
    if (!out.summary && raw.table && typeof raw.table === 'string' && raw.table.includes('|')) {
      out.summary = raw.table;
      out.output_type = out.output_type || 'markdown';
    }
    if (!out.summary && raw.raw_output && raw.raw_output.table && typeof raw.raw_output.table === 'string' && raw.raw_output.table.includes('|')) {
      out.summary = raw.raw_output.table;
      out.output_type = out.output_type || 'markdown';
    }

    if (raw.vega_spec) out.vega_spec = raw.vega_spec;
    if (raw.vegaSpec) out.vegaSpec = raw.vegaSpec;
    if (raw.image_base64) out.image_base64 = raw.image_base64;
    else if (raw.imageBase64) out.imageBase64 = raw.imageBase64;
    else if (raw.raw_output && raw.raw_output.image_base64) out.image_base64 = raw.raw_output.image_base64;
    else if (raw.raw_output && raw.raw_output.imageBase64) out.imageBase64 = raw.raw_output.imageBase64;

    if (out.summary && typeof out.summary === 'object') {
      try {
        out.summary = JSON.stringify(out.summary, null, 2);
      } catch (e) {
        out.summary = String(out.summary);
      }
    }

    if (raw.type) out.output_type = raw.type;
    return out;
  };

  const handleSubmit = async () => {
    if (!query.trim() || loading) return;

    setLoading(true);
    setResults(null);

    try {
      const startTime1 = performance.now();
      const startTime2 = performance.now();
      const startTime3 = performance.now();

      const settledResults = await Promise.allSettled([
        fetch(API_ENDPOINTS.api1, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'ngrok-skip-browser-warning': '69420' },
          body: JSON.stringify({ query })
        }).then(async (r) => {
          const data = await r.json();
          if (!r.ok) throw new Error(data?.detail || data?.error || "API error");
          return data;
        }).then(data => ({ data, time: performance.now() - startTime1 })),

        fetch(API_ENDPOINTS.api2, {
          method: 'POST',
          headers: { 
            'Content-Type': 'application/json', 
            'ngrok-skip-browser-warning': '69420',
            'x-api-key': process.env.REACT_APP_API2_KEY
          },
          body: JSON.stringify({ query })
        }).then(async (r) => {
          const data = await r.json();
          if (!r.ok) throw new Error(data?.detail || data?.error || "API error");
          return data;
        }).then(data => ({ data, time: performance.now() - startTime2 })),

        fetch(API_ENDPOINTS.api3, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'ngrok-skip-browser-warning': '69420' },
          body: JSON.stringify({ query })
        }).then(async (r) => {
          const data = await r.json();
          if (!r.ok) throw new Error(data?.detail || data?.error || "API error");
          return data;
        }).then(data => ({ data, time: performance.now() - startTime3 }))
      ]);

      const result1 = settledResults[0].status === "fulfilled"
        ? settledResults[0].value.data
        : { output_type: "text", summary: settledResults[0].reason?.message || "API failed" };
      const time1 = settledResults[0].status === "fulfilled" ? settledResults[0].value.time : 0;

      const result2 = settledResults[1].status === "fulfilled"
        ? settledResults[1].value.data
        : { output_type: "text", summary: settledResults[1].reason?.message || "API failed" };
      const time2 = settledResults[1].status === "fulfilled" ? settledResults[1].value.time : 0;

      const normalizedResult2 = normalizeApi2(result2);

      const result3 = settledResults[2].status === "fulfilled"
        ? settledResults[2].value.data
        : { output_type: "text", summary: settledResults[2].reason?.message || "API failed" };
      const time3 = settledResults[2].status === "fulfilled" ? settledResults[2].value.time : 0;

      const relevancyResults = await Promise.allSettled([
        calculateRelevancy(query, result1),
        calculateRelevancy(query, normalizedResult2 || result2),
        calculateRelevancy(query, result3)
      ]);

      const rel1 = relevancyResults[0].status === 'fulfilled' ? relevancyResults[0].value : 0;
      const rel2 = relevancyResults[1].status === 'fulfilled' ? relevancyResults[1].value : 0;
      const rel3 = relevancyResults[2].status === 'fulfilled' ? relevancyResults[2].value : 0;

      setResults({
        api1: { data: result1, relevancy: rel1, fetchTime: time1, name: 'VEGA-LITE' },
        api2: { data: normalizedResult2 || result2, relevancy: rel2, fetchTime: time2, name: 'LLM BASED' },
        api3: { data: result3, relevancy: rel3, fetchTime: time3, name: 'VLM BASED' }
      });

    } catch (error) {
      console.error('Error fetching results:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const renderTable = (tableData, showMaximize = false) => {
  if (!tableData || !tableData.headers || !tableData.rows) return null;
  
  return (
    <div className="relative">
      {showMaximize && (
        <button
          onClick={() => setFullscreenTable(tableData)}
          className="absolute top-2 right-2 z-20 luxury-button text-white p-2 rounded-lg transition-all"
          title="Maximize table"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6v12h12v-4m7-7V3m0 0h-4m4 0v4" />
          </svg>
        </button>
      )}
      {/* ADD SCROLLBAR WITH MAXHEIGHT */}
      <div className="overflow-auto luxury-scroll my-4 rounded-xl border border-amber-500/20" style={{ maxHeight: '250px' }}>
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10" style={{ backgroundColor: '#0f172a' }}>
            <tr className="bg-gradient-to-r from-amber-600/20 via-blue-600/20 to-amber-600/20">
              {tableData.headers.map((h, i) => (
                <th key={i} className="border border-amber-400/30 px-4 py-3 text-left font-bold text-amber-100 uppercase tracking-wide">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tableData.rows.map((row, i) => (
              <tr key={i} className="hover:bg-amber-500/5 transition-colors">
                {row.map((cell, j) => (
                  <td key={j} className="border border-slate-700/50 px-4 py-2 text-gray-200">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

  const VegaChart = ({ spec, containerId, onMaximize }) => {
    useEffect(() => {
      if (window.vegaEmbed && spec) {
        const enhancedSpec = {
          ...spec,
          width: "container",
          height: 400,
          autosize: { type: "fit", contains: "padding" },
          config: {
            view: { stroke: null, fill: "#0f172a" },
            axis: {
              labelColor: "#cbd5e1",
              titleColor: "#f1f5f9",
              gridColor: "#334155",
              domainColor: "#d97706"
            },
            legend: { labelColor: "#cbd5e1", titleColor: "#f1f5f9" },
            title: { color: "#fbbf24", fontSize: 16, fontWeight: 600 }
          }
        };

        window.vegaEmbed(`#${containerId}`, enhancedSpec, {
          actions: { export: true, source: false, compiled: false, editor: false },
          theme: 'dark',
          renderer: 'canvas'
        }).catch(err => console.error('Vega embed error:', err));
      }
    }, [spec, containerId]);

    return (
      <div className="relative w-full">
        <button
          onClick={() => onMaximize && onMaximize(spec)}
          className="absolute top-2 right-2 z-20 luxury-button text-white p-2 rounded-lg transition-all"
          title="Maximize graph"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6v12h12v-4m7-7V3m0 0h-4m4 0v4" />
          </svg>
        </button>
        <div className="w-full overflow-x-auto glass-card rounded-lg p-2">
          <div id={containerId} className="min-w-[400px] flex justify-center"></div>
        </div>
      </div>
    );
  };

  const renderContent = (data, apiIndex) => {
    if (!data) return <p className="text-gray-400">No content available</p>;

    const outputType = data.output_type || 'text';
    const summary = data.summary || '';
    const vegaSpec = data.vega_spec || data.vegaSpec;
    const imageBase64 = data.image_base64 || data.imageBase64;
    const imageSrc = imageBase64
      ? (typeof imageBase64 === 'string' && imageBase64.startsWith('data:')
          ? imageBase64
          : `data:image/png;base64,${imageBase64}`)
      : null;

    const isApi1 = apiIndex === 1;
    const isMarkdownTable = (isApi1 && outputType === 'markdown') || (apiIndex === 2 && outputType === 'markdown');

    return (
      <div className="space-y-4">
        {/* 🔹 API-2 IMAGE FIRST (TOP) */}
{imageSrc && apiIndex === 2 && (
  <div className="glass-card rounded-lg p-4 border border-blue-500/20">
    <h4 className="text-sm font-semibold text-blue-400 mb-2 flex items-center gap-2">
      <Sparkles className="w-4 h-4" />
      Image Output:
    </h4>
    <div className="flex justify-center">
      <img
        src={imageSrc}
        alt="API2 output"
        className="max-w-full rounded-md border border-amber-500/20"
      />
    </div>
  </div>
)}

        {isMarkdownTable && (
          <div className="relative">
            <button
              onClick={() => {
                // Extract summary from markdown content
                const lines = summary.split('\n');
                const tableStartIndex = lines.findIndex(line => line.includes('|'));
                const summaryText = lines.slice(0, tableStartIndex).join('\n').trim();
                const tableContent = lines.slice(tableStartIndex).join('\n');
                
                setFullscreenTable({ 
                  type: 'markdown', 
                  content: tableContent,
                  summary: summaryText
                });
              }}
              className="absolute top-2 right-2 z-20 luxury-button text-white p-2 rounded-lg transition-all"
              title="Maximize table"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6v12h12v-4m7-7V3m0 0h-4m4 0v4" />
              </svg>
            </button>
            <div className="luxury-markdown-table glass-card rounded-xl p-6 border border-amber-500/30 overflow-x-auto">
              <ReactMarkdown
              remarkPlugins={[remarkGfm]}
                components={{
                  table: ({ node, ...props }) => (
                    <table className="w-full border-collapse text-sm md:text-base" {...props} />
                  ),
                  thead: ({ node, ...props }) => (
                    <thead className="sticky top-0 z-10 bg-gradient-to-r from-amber-600/40 to-blue-600/40 backdrop-blur" {...props} />
                  ),
                  tr: ({ node, ...props }) => (
                    <tr className="even:bg-slate-800/40 odd:bg-slate-900/40 hover:bg-amber-500/15 transition-colors" {...props} />
                  ),
                  th: ({ node, ...props }) => (
                    <th className="border border-amber-400/30 px-4 py-3 text-left font-bold uppercase tracking-wide text-amber-100 whitespace-nowrap" {...props} />
                  ),
                  td: ({ node, children, ...props }) => {
                    const isNumber = typeof children === 'string' && !isNaN(children);
                    return (
                      <td
                        className={`border border-amber-400/20 px-4 py-2 ${
                          isNumber ? 'text-right font-mono text-blue-300' : 'text-left text-gray-200'
                        } whitespace-nowrap`}
                        {...props}
                      >
                        {children}
                      </td>
                    );
                  },
                  p: ({ node, ...props }) => (
                    <p className="text-white mb-4 leading-relaxed" {...props} />
                  ),
                  h3: ({ node, ...props }) => (
                    <h3 className="text-amber-400 font-bold text-lg mb-2" {...props} />
                  ),
                  strong: ({ node, ...props }) => (
                    <strong className="text-amber-300 font-semibold" {...props} />
                  )
                }}
              >
                {summary}
              </ReactMarkdown>
            </div>
          </div>
        )}
        
       {vegaSpec && vegaLoaded && (
  <div className="space-y-3">

    {/* 🔹 GRAPH FIRST */}
    <div className="glass-card rounded-lg border border-blue-500/20 p-4">
      <h4 className="text-sm font-semibold text-blue-400 mb-3 flex items-center gap-2">
        <Sparkles className="w-4 h-4" />
        Visualization:
      </h4>
      <VegaChart
        spec={vegaSpec}
        containerId={`vega-chart-${apiIndex}`}
        onMaximize={(spec) => setFullscreenSpec(spec)}
      />
    </div>

    {/* 🔹 SUMMARY BELOW GRAPH */}
    {summary && !isMarkdownTable && (
      <div className="glass-card rounded-lg p-4 border border-amber-500/20">
        <h4 className="text-sm font-semibold text-amber-400 mb-2 flex items-center gap-2">
          <Sparkles className="w-4 h-4" />
          Analysis:
        </h4>
        <p className="text-gray-200 leading-relaxed text-sm">{summary}</p>
      </div>
    )}

  </div>
)}


        {!vegaSpec && !isMarkdownTable && summary && (
          <div className="glass-card rounded-lg p-4 border border-amber-500/20">
            <h4 className="text-sm font-semibold text-amber-400 mb-2 flex items-center gap-2">
              <Sparkles className="w-4 h-4" />
              Response:
            </h4>
            {apiIndex === 2 ? (
              <div className="text-gray-200 leading-relaxed text-sm">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    table: ({ node, ...props }) => (
                      <table className="w-full border-collapse text-sm md:text-base" {...props} />
                    ),
                    thead: ({ node, ...props }) => (
                      <thead className="sticky top-0 z-10 bg-gradient-to-r from-amber-600/40 to-blue-600/40 backdrop-blur" {...props} />
                    ),
                    tr: ({ node, ...props }) => (
                      <tr className="even:bg-slate-800/40 odd:bg-slate-900/40 hover:bg-amber-500/15 transition-colors" {...props} />
                    ),
                    th: ({ node, ...props }) => (
                      <th className="border border-amber-400/30 px-4 py-3 text-left font-bold uppercase tracking-wide text-amber-100 whitespace-nowrap" {...props} />
                    ),
                    td: ({ node, children, ...props }) => {
                      const text = Array.isArray(children) ? children.join('') : children;
                      const isNumber = typeof text === 'string' && !isNaN(text.replace(/[,₹â¹\s]/g, ''));
                      return (
                        <td
                          className={`border border-amber-400/20 px-4 py-2 ${
                            isNumber ? 'text-right font-mono text-blue-300' : 'text-left text-gray-200'
                          } whitespace-nowrap`}
                          {...props}
                        >
                          {children}
                        </td>
                      );
                    }
                  }}
                >
                  {summary}
                </ReactMarkdown>
              </div>
            ) : (
              <p className="text-gray-200 leading-relaxed text-sm whitespace-pre-wrap">{summary}</p>
            )}
          </div>
        )}

        {data.value !== undefined && (
          <div className="glass-card rounded-lg p-6 border border-amber-500/30 text-center gold-glow">
            <h4 className="text-sm font-semibold text-amber-400 mb-2">Value:</h4>
            <p className="text-5xl font-bold gold-gradient-text">
              {data.value}
            </p>
          </div>
        )}

        {imageBase64 && Array.isArray(imageBase64) && apiIndex === 3 && (
          <div className="glass-card rounded-lg p-4 border border-blue-500/20">
            <h4 className="text-sm font-semibold text-blue-400 mb-2">Image Output:</h4>
            <div className="flex flex-col gap-4">
              {imageBase64.map((b64, idx) => (
                <img key={idx} src={typeof b64 === 'string' && b64.startsWith('data:') ? b64 : `data:image/png;base64,${b64}`} alt={`API3 output ${idx}`} className="max-w-full rounded-md border border-amber-500/20" />
              ))}
            </div>
          </div>
        )}

        {data.table && (
          <div>
            <h4 className="text-sm font-semibold text-amber-400 mb-2">Table:</h4>
            {renderTable(data.table, true)}
          </div>
        )}
      </div>
    );
  };

  const APICard = ({ apiData, color, index }) => {
    const colorSchemes = {
      purple: {
        gradient: 'from-amber-600 via-amber-500 to-blue-600',
        border: 'border-amber-500/30',
        text: 'text-amber-300',
        headerBg: 'from-amber-600/90 to-blue-600/90'
      },
      pink: {
        gradient: 'from-blue-600 via-amber-500 to-blue-700',
        border: 'border-blue-500/30',
        text: 'text-blue-300',
        headerBg: 'from-blue-600/90 to-amber-600/90'
      },
      blue: {
        gradient: 'from-amber-500 via-blue-600 to-amber-600',
        border: 'border-amber-500/30',
        text: 'text-amber-300',
        headerBg: 'from-amber-600/90 to-blue-700/90'
      }
    };

    const scheme = colorSchemes[color];

    return (
      <div className="card-3d-luxury">
        <div className="glass-card rounded-2xl border-gold-gradient overflow-hidden">
          <div className={`bg-gradient-to-r ${scheme.headerBg} p-4 backdrop-blur-sm`}>
            <h3 className="text-xl font-bold text-white flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-amber-300" />
              {apiData.name}
            </h3>
          </div>

          <div className="p-6 space-y-4">
            <div className="glass-card rounded-xl p-4 border border-white/10">
              <p className={`text-sm ${scheme.text} mb-2 font-semibold flex items-center gap-2`}>
                <span className="w-2 h-2 rounded-full bg-amber-400"></span>
                User Query:
              </p>
              <p className="text-gray-200 text-sm">{query}</p>
            </div>

            <div className="glass-card rounded-xl p-4 border border-white/10 max-h-[420px] overflow-auto luxury-scroll">
              <p className={`text-sm ${scheme.text} mb-3 font-semibold flex items-center gap-2`}>
                <span className="w-2 h-2 rounded-full bg-blue-400"></span>
                Response:
              </p>
              {renderContent(apiData.data, index)}
            </div>

            <div className="glass-card rounded-xl p-4 border border-amber-500/20 gold-glow">
              <div className="flex items-center justify-between mb-2">
                <span className="text-amber-300 font-semibold flex items-center gap-2 text-sm">
                  <TrendingUp className="w-4 h-4" />
                  Relevancy Score
                </span>
                <span className="text-2xl font-bold gold-gradient-text">
                  {typeof apiData.relevancy === 'number'
                    ? `${apiData.relevancy}%`
                    : typeof apiData.relevancy === 'object' && apiData.relevancy?.score
                      ? `${apiData.relevancy.score}%`
                      : 'N/A'}
                </span>
              </div>
              <div className="w-full bg-slate-700/50 rounded-full h-3 overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-amber-500 via-amber-400 to-blue-500 rounded-full transition-all duration-1000 gold-glow"
                  style={{ width: `${apiData.relevancy || 0}%` }}
                />
              </div>
            </div>

            <div className="glass-card rounded-xl p-4 border border-blue-500/20 blue-glow">
              <div className="flex items-center justify-between">
                <span className="text-blue-300 font-semibold flex items-center gap-2 text-sm">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Response Time
                </span>
                <span className="text-2xl font-bold text-blue-400">
                  {apiData.fetchTime < 1000 
                    ? `${Math.round(apiData.fetchTime)}ms`
                    : `${(apiData.fetchTime / 1000).toFixed(2)}s`
                  }
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-screen luxury-bg noise-overlay elegant-vignette p-4 md:p-8 relative overflow-hidden">
      <div className="floating-orb orb-white"></div>
      <div className="floating-orb orb-gold"></div>
      <div className="floating-orb orb-blue"></div>
      <div className="gold-particles"></div>

      <div className="max-w-7xl mx-auto relative z-10">
        <div className="text-center mb-8 md:mb-12 sparkle-container">
          <h1 className="text-4xl md:text-6xl font-bold leading leading-[1.2]
  pt-2
  pb-2 gold-gradient-text">
            Multi-Agent AI Analysis Dashboard
          </h1>
          <p className="text-gray-300 text-base md:text-lg font-light">
            Compare, visualize, and evaluate responses from multiple AI systems
          </p>
        </div>

        <div className="mb-8 md:mb-12">
          <div className="relative group">
            <div className="absolute -inset-1 bg-gradient-to-r from-amber-600 via-blue-600 to-amber-600 rounded-2xl blur opacity-30 group-hover:opacity-50 transition duration-1000"></div>
            <div className="relative glass-card rounded-2xl p-2 border-gold-gradient">
              <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Enter your query here..."
                  disabled={loading}
                  className="flex-1 bg-transparent px-6 py-4 text-white placeholder-gray-400 focus:outline-none text-lg"
                />
                <button
                  onClick={handleSubmit}
                  disabled={loading || !query.trim()}
                  className="luxury-button text-white px-8 py-4 rounded-xl font-semibold disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" />
                      Processing...
                    </>
                  ) : (
                    <>
                      <Send className="w-5 h-5" />
                      Analyze
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>

        {results && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <APICard apiData={results.api1} color="purple" index={1} />
            <APICard apiData={results.api2} color="pink" index={2} />
            <APICard apiData={results.api3} color="blue" index={3} />
          </div>
        )}

        {fullscreenSpec && (
          <div className="fixed inset-0 z-50 bg-black/90 backdrop-blur-sm flex items-center justify-center p-4">
            <div className="glass-card rounded-2xl border-gold-gradient w-full h-[90vh] flex flex-col overflow-hidden">
              <div className="bg-gradient-to-r from-amber-600 to-blue-600 p-4 flex justify-between items-center">
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <Sparkles className="w-5 h-5" />
                  Fullscreen Visualization
                </h2>
                <button
                  onClick={() => setFullscreenSpec(null)}
                  className="bg-red-600 hover:bg-red-700 text-white p-2 rounded-lg transition-colors"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              
             <div className="flex-1 overflow-auto p-6 bg-slate-900/50 luxury-scroll-full">

                <div id="fullscreen-vega" style={{ height: '100%', width: '100%' }}></div>
              </div>
            </div>
          </div>
        )}

        {/* Fullscreen Table Modal */}
{fullscreenTable && (
  <div className="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">
    <div className="bg-slate-900 rounded-2xl border-2 border-amber-500/50 w-full max-w-7xl h-[90vh] flex flex-col overflow-hidden shadow-2xl">
      <div className="bg-gradient-to-r from-amber-600 to-blue-600 p-4 flex justify-between items-center flex-shrink-0">
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <Sparkles className="w-5 h-5" />
          Fullscreen Table View
        </h2>
        <button
          onClick={() => setFullscreenTable(null)}
          className="bg-red-600 hover:bg-red-700 text-white p-2 rounded-lg transition-colors"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      
      <div className="flex-1 overflow-auto p-8 bg-slate-900 luxury-scroll-full">
        {fullscreenTable.type === 'markdown' ? (
          <div className="space-y-6">
            {/* Summary Section - FIXED */}
            {fullscreenTable.summary && fullscreenTable.summary.trim() && (
              <div className="bg-slate-800/80 rounded-xl p-6 border-2 border-amber-500/40">
                <h3 className="text-xl font-bold text-amber-400 mb-4 flex items-center gap-2">
                  <Sparkles className="w-5 h-5" />
                  Summary
                </h3>
                <div className="text-white leading-relaxed text-lg space-y-3">
                  {fullscreenTable.summary.split('\n').map((line, i) => (
                    line.trim() && <p key={i}>{line}</p>
                  ))}
                </div>
              </div>
            )}
            
            {/* Table Section - FIXED */}
            <div className="bg-slate-800/80 rounded-xl p-6 border-2 border-blue-500/40">
              <h3 className="text-xl font-bold text-blue-400 mb-4 flex items-center gap-2">
                <Sparkles className="w-5 h-5" />
                Data Table
              </h3>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  table: ({ node, ...props }) => (
                    <table className="w-full border-collapse text-base bg-slate-900/50" {...props} />
                  ),
                  thead: ({ node, ...props }) => (
                    <thead className="bg-gradient-to-r from-amber-600/60 to-blue-600/60" {...props} />
                  ),
                  tr: ({ node, ...props }) => (
                    <tr className="border-b border-slate-700 hover:bg-amber-500/10 transition-colors" {...props} />
                  ),
                  th: ({ node, ...props }) => (
                    <th className="border border-amber-400/40 px-6 py-4 text-left font-bold uppercase tracking-wide text-amber-100 bg-slate-800/50" {...props} />
                  ),
                  td: ({ node, children, ...props }) => {
                    const isNumber = typeof children === 'string' && !isNaN(children);
                    return (
                      <td
                        className={`border border-slate-700 px-6 py-4 ${
                          isNumber ? 'text-right font-mono text-blue-300 font-semibold' : 'text-left text-white'
                        }`}
                        {...props}
                      >
                        {children}
                      </td>
                    );
                  },
                }}
              >
                {fullscreenTable.content}
              </ReactMarkdown>
            </div>
          </div>
        ) : (
          <div className="bg-slate-800/80 rounded-xl p-6 border-2 border-amber-500/40">
            {renderTable(fullscreenTable, false)}
          </div>
        )}
      </div>
    </div>
  </div>
)}
        {loading && (
          <div className="flex justify-center items-center py-20">
            <div className="relative">
              <div className="w-20 h-20 border-4 border-amber-500/30 border-t-amber-500 rounded-full animate-spin luxury-spinner"></div>
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-12 h-12 border-4 border-blue-500/30 border-t-blue-500 rounded-full animate-spin luxury-spinner"></div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default MultiAPIQueryApp;