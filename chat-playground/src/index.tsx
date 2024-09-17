import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import reportWebVitals from './reportWebVitals';

const consErr = console.error;
console.error = (...args) => {
  try{
    if (typeof args[0] === "string" 
      && (args[0].indexOf("Support for defaultProps will be removed ") > -1   // Suppress ridiculous warning from react - given we have very little control over library code #EYEROLL
      || args[0].indexOf("Warning:") > -1)                                    // Suppress the multitude of warnings from React that are not useful given how little control we have over the library 
      ) {  
        let msg = args[0].length > 150 ? args[0].substring(0, 150) + "..." : args[0];
      console.warn("Suppressed Error Log:", msg);
      return;
    }
    consErr(...args);
  } catch(e) {
    console.warn("Error in console.error override", e);
  }
}


const root = ReactDOM.createRoot(
  document.getElementById('root') as HTMLElement
);
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();
