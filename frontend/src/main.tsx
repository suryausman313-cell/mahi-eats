import React from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter} from 'react-router-dom';
import App from './App';
import './styles.css';

// Kiosk/app-like viewport: keep the UI at one stable scale while allowing normal vertical scrolling.
document.addEventListener('gesturestart',(e)=>e.preventDefault(),{passive:false} as AddEventListenerOptions);
document.addEventListener('touchmove',(e)=>{if((e as TouchEvent).touches.length>1)e.preventDefault()},{passive:false});
window.addEventListener('wheel',(e)=>{if(e.ctrlKey)e.preventDefault()},{passive:false});

action();
function action(){createRoot(document.getElementById('root')!).render(<React.StrictMode><BrowserRouter><App/></BrowserRouter></React.StrictMode>)}
if('serviceWorker' in navigator){window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{}))}
