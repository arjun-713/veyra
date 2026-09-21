const FALLBACK_LOCALE = 'en-US';

export function safeLocale(value: string | undefined | null): string {
 if(!value || value==='C' || value==='POSIX')return FALLBACK_LOCALE;
 try {
  new Intl.NumberFormat(value);
  return value;
 } catch {
  return FALLBACK_LOCALE;
 }
}

/**
 * WebKitGTK can expose the POSIX `C` locale as navigator.language. That is
 * not a BCP-47 language tag and makes libraries that construct Intl formatters
 * fail during module evaluation. Normalize it before loading the renderer.
 */
export function normalizeNavigatorLocale(target: Pick<Navigator,'language'> = navigator): string {
 const locale=safeLocale(target.language);
 if(locale!==target.language){
  try{Object.defineProperty(target,'language',{configurable:true,value:locale});}catch{/* readonly host object */}
 }
 return locale;
}
