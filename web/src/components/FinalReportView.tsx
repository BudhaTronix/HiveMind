import { ExternalLink, FileCheck2, X } from 'lucide-react'
import type { FinalReport } from '../types'

export function FinalReportView({ report, onClose }: { report: FinalReport; onClose: () => void }) {
  return <div className="report-overlay"><article className="final-report" role="dialog" aria-modal="true" aria-labelledby="report-title"><header><div><span className="eyebrow"><FileCheck2 size={14} /> Validated final output</span><h2 id="report-title">{report.title}</h2></div><button className="icon-button" aria-label="Close final report" onClick={onClose}><X size={18} /></button></header><section className="report-lead"><h3>Executive summary</h3><p>{report.executive_summary}</p></section><section><h3>Direct answer</h3><p>{report.answer}</p></section><section><h3>Key findings</h3><ul className="finding-list">{report.key_findings.map((item) => <li className={findingClass(item)} key={item}>{item}</li>)}</ul></section><div className="report-columns"><List title="Recommendations" values={report.recommendations} /><List title="Risks" values={report.risks} /><List title="Uncertainties" values={report.uncertainties} /><List title="Research limitations" values={report.research_limitations} /></div><section><h3>Evidence sources</h3><div className="source-list">{report.sources.map((source) => <article key={source.evidence_id}><span className={`verification ${source.verification_status}`}>{source.verification_status.replaceAll('_', ' ')}</span><strong>{source.title}</strong>{source.url && <a href={source.url} target="_blank" rel="noreferrer">Open source <ExternalLink size={13} /></a>}</article>)}</div></section></article></div>
}

function List({ title, values }: { title: string; values: string[] }) {
  if (!values.length) return null
  return <section><h3>{title}</h3><ul>{values.map((item) => <li key={item}>{item}</li>)}</ul></section>
}

function findingClass(value: string): string {
  return `finding ${value.toLowerCase().startsWith('verified') ? 'verified' : value.toLowerCase().startsWith('partially') ? 'partial' : value.toLowerCase().startsWith('contradicted') ? 'contradicted' : 'uncertain'}`
}
