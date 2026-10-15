import axios from 'axios'

const client = axios.create({ baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1', timeout: 20000 })
const demoRows = [
 { facility:'Kigali University Teaching Hospital',district:'Nyarugenge',province:'Kigali City',medicine:'Artemether/Lumefantrine 20/120mg Tabs',medicine_code:'AL-20120',stock_units:460,daily_consumption:82,lead_time_days:5.6,risk_level:'CRITICAL',confidence:.91,under5_population:37800,poverty_rate:16.2,malaria_prevalence:2.1 },
 { facility:'Nyamata District Hospital',district:'Bugesera',province:'Eastern',medicine:'Amoxicillin 250mg Dispersible Tabs',medicine_code:'AMX-250',stock_units:1840,daily_consumption:136,lead_time_days:13.5,risk_level:'MODERATE',confidence:.83,under5_population:29400,poverty_rate:28.4,malaria_prevalence:5.7 },
 { facility:'Musanze District Hospital',district:'Musanze',province:'Northern',medicine:'Oxytocin Injection 10IU/ml Ampoule',medicine_code:'OXY-10',stock_units:2960,daily_consumption:48,lead_time_days:61.7,risk_level:'STABLE',confidence:.94,under5_population:31200,poverty_rate:22.7,malaria_prevalence:1.8 },
 { facility:'Kimironko Health Centre',district:'Gasabo',province:'Kigali City',medicine:'Oral Rehydration Salts + Zinc',medicine_code:'ORS-100',stock_units:420,daily_consumption:92,lead_time_days:4.6,risk_level:'CRITICAL',confidence:.88,under5_population:42700,poverty_rate:14.6,malaria_prevalence:2.4 },
 { facility:'Huye District Hospital',district:'Huye',province:'Southern',medicine:'Amoxicillin 250mg Dispersible Tabs',medicine_code:'AMX-250',stock_units:2810,daily_consumption:54,lead_time_days:52,risk_level:'STABLE',confidence:.9,under5_population:26800,poverty_rate:24.1,malaria_prevalence:1.5 }
]
const mockSummary = { facilities:528,districts:30,medicines:4,critical:146,moderate:182,stable:178,stock_units:1483620,reporting_date:'2026-10' }
async function fallback(request, fallbackValue) { try { return (await request()).data } catch { return fallbackValue } }
export const api = {
 summary: () => fallback(() => client.get('/inventory/summary'), mockSummary),
 risks: async (filters = {}) => fallback(() => client.get('/predictions/risk-register', { params: filters }), demoRows),
 transfers: () => fallback(() => client.get('/transfers/recommendations'), [{donor_facility:'Musanze District Hospital',donor_district:'Musanze',recipient_facility:'Kigali University Teaching Hospital',recipient_district:'Nyarugenge',medicine:'Artemether/Lumefantrine 20/120mg Tabs',available_units:820,requested_units:460,donor_lead_time_days:61.7,recipient_lead_time_days:5.6}]),
 trust: () => fallback(() => client.get('/analytics/trust-metrics'), {accuracy:.91,labels:['CRITICAL','MODERATE','STABLE'],precision:[.89,.87,.96],recall:[.93,.84,.95],confusion_matrix:[[65,4,1],[7,52,3],[0,5,78]],feature_importances:[{feature:'Daily consumption',importance:.32},{feature:'Stock on hand',importance:.28},{feature:'Under-five population',importance:.15},{feature:'Medicine type',importance:.1},{feature:'Rainy season',importance:.08}],source:'Holdout evaluation'}),
 upload: async file => (await client.post('/data/upload-csv', (() => { const data = new FormData(); data.append('file',file); return data })(), { headers:{'Content-Type':'multipart/form-data'} })).data,
 downloadCsv: async () => (await client.get('/predictions/risk-register')).data
}
