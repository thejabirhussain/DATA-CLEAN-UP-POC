import React from 'react'
import { Link, Route, Routes, NavLink } from 'react-router-dom'
import Home from './pages/Home.jsx'
import Diagnostics from './pages/Diagnostics.jsx'
import Prep from './pages/Prep.jsx'
import DocumentQA from './pages/DocumentQA.jsx'

function Layout({ children }){
  return (
    <div className="min-h-screen">
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-emerald-600 flex items-center justify-center text-white font-bold">C</div>
          <div className="flex-1">
            <h1 className="text-lg font-semibold">Complyia • Data Tools</h1>
            <p className="text-xs text-slate-500">Data Clean & Prep • Diagnostics • Reconciliation</p>
          </div>
          <nav className="flex items-center gap-2 text-sm">
            <NavLink to="/" end className={({isActive})=>`px-3 py-1 rounded-lg ${isActive? 'bg-emerald-50 text-emerald-700' : 'text-slate-700 hover:bg-slate-50'}`}>Clean & Prep</NavLink>
            <NavLink to="/diagnostics" className={({isActive})=>`px-3 py-1 rounded-lg ${isActive? 'bg-emerald-50 text-emerald-700' : 'text-slate-700 hover:bg-slate-50'}`}>Diagnostics</NavLink>
            <NavLink to="/prep" className={({isActive})=>`px-3 py-1 rounded-lg ${isActive? 'bg-emerald-50 text-emerald-700' : 'text-slate-700 hover:bg-slate-50'}`}>Clean & Prep (Advanced)</NavLink>
            <NavLink to="/document-qa" className={({isActive})=>`px-3 py-1 rounded-lg ${isActive? 'bg-emerald-50 text-emerald-700' : 'text-slate-700 hover:bg-slate-50'}`}>Document Q&A</NavLink>
          </nav>
        </div>
      </header>
      {children}
    </div>
  )
}

export default function App(){
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Home/>} />
        <Route path="/diagnostics" element={<Diagnostics/>} />
        <Route path="/prep" element={<Prep/>} />
        <Route path="/document-qa" element={<DocumentQA/>} />
      </Routes>
    </Layout>
  )
}
