//! SDK des plugins Voktora en Rust (API de plugins v5).
//!
//! ```ignore
//! use voktora_plugin::{plugin, Api, json};
//!
//! plugin!(on_load, on_unload);
//!
//! fn on_load(api: &Api) {
//!     api.options().add_bool("fort", "Message fort", true);
//!     api.add_menu_action("Outils", "Dire bonjour", |api, _ctx| {
//!         api.message("Rust", "Bonjour depuis Rust !");
//!     });
//! }
//! fn on_unload(_api: &Api) {}
//! ```
//!
//! Tout ce que l'API Python offre est joignable avec [`Api::call`] (mêmes noms, en snake_case, arguments en JSON) ;
//! les méthodes typées ci-dessous ne sont que des raccourcis. Les permissions sont vérifiées par l'application (et
//! détectées automatiquement depuis votre code par `plugin_tool detect`).
//!
//! ATTENTION : un plugin Rust est du code NATIF — Voktora ne peut pas le restreindre (réseau, fichiers, processus).
//! Le marketplace ne l'accepte qu'au niveau officiel.

use std::collections::HashMap;
use std::ffi::{c_char, CStr, CString};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

pub use serde_json as json;
pub use serde_json::{json, Value};

pub type HostCall = extern "C" fn(*const c_char) -> *mut c_char;
pub type HostFree = extern "C" fn(*mut c_char);

/// Rappel Rust appelable par l'application : reçoit l'API et le contexte (`{"projectPath", "data", "args"}`).
pub type Callback = Arc<dyn Fn(&Api, Value) -> Value + Send + Sync>;

static HOST: OnceLock<(HostCall, HostFree)> = OnceLock::new();
static NEXT_ID: AtomicU64 = AtomicU64::new(1);

fn callbacks() -> &'static Mutex<HashMap<u64, Callback>> {
    static CB: OnceLock<Mutex<HashMap<u64, Callback>>> = OnceLock::new();
    CB.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Point d'entrée vers l'application. Sans état : copiez-la où vous voulez.
#[derive(Clone, Copy, Default)]
pub struct Api;

/// Réglages du plugin (voir `api.options()`), affichés et enregistrés par Voktora.
#[derive(Clone, Copy, Default)]
pub struct Options;

impl Api {
    /// Appelle une méthode de l'API de plugins : `api.call("notify", json!(["Salut"]))`.
    /// Les arguments sont un tableau JSON. Retourne la valeur ou le message d'erreur (permission refusée…).
    pub fn call(&self, name: &str, args: Value) -> Result<Value, String> {
        raw_call(name, args)
    }

    /// Comme [`Api::call`] avec un rappel Rust à la place d'un argument : mettez `callback(|api, ctx| …)`
    /// dans le tableau d'arguments.
    pub fn options(&self) -> Options {
        Options
    }

    pub fn log(&self, message: &str) {
        let _ = self.call("log", json!([message]));
    }
    pub fn warn(&self, message: &str) {
        let _ = self.call("warn", json!([message]));
    }
    pub fn notify(&self, message: &str) {
        let _ = self.call("notify", json!([message]));
    }
    pub fn message(&self, title: &str, text: &str) {
        let _ = self.call("message", json!([title, text]));
    }
    pub fn confirm(&self, title: &str, text: &str) -> bool {
        self.call("confirm", json!([title, text])).ok().and_then(|v| v.as_bool()).unwrap_or(false)
    }
    pub fn add_menu_action<F>(&self, menu: &str, label: &str, handler: F)
    where
        F: Fn(&Api, Value) -> () + Send + Sync + 'static,
    {
        let id = register(Arc::new(move |api, ctx| {
            handler(api, ctx);
            Value::Null
        }));
        let _ = self.call("add_menu_action", json!([menu, label, {"__fn": id}]));
    }
    pub fn add_button<F>(&self, label: &str, handler: F)
    where
        F: Fn(&Api, Value) -> () + Send + Sync + 'static,
    {
        let id = register(Arc::new(move |api, ctx| {
            handler(api, ctx);
            Value::Null
        }));
        let _ = self.call("register_button", json!([label, {"__fn": id}]));
    }
    /// S'abonne à un événement (`"on_open"`, `"on_start"`, `"on_plugin_loaded"`…).
    pub fn on<F>(&self, event: &str, handler: F)
    where
        F: Fn(&Api, Value) -> () + Send + Sync + 'static,
    {
        let id = register(Arc::new(move |api, ctx| {
            handler(api, ctx);
            Value::Null
        }));
        let _ = self.call("on", json!([event, {"__fn": id}]));
    }
    /// Appelle `handler` toutes les `seconds` secondes (au moins 0,2).
    pub fn every<F>(&self, seconds: f64, handler: F)
    where
        F: Fn(&Api, Value) -> () + Send + Sync + 'static,
    {
        let id = register(Arc::new(move |api, ctx| {
            handler(api, ctx);
            Value::Null
        }));
        let _ = self.call("every", json!([seconds, {"__fn": id}]));
    }
}

impl Options {
    fn call(&self, name: &str, args: Value) -> Result<Value, String> {
        raw_call(&format!("options.{name}"), args)
    }
    pub fn group(&self, name: &str) {
        let _ = self.call("group", json!([name]));
    }
    pub fn add_bool(&self, key: &str, label: &str, default: bool) {
        let _ = self.call("add_bool", json!([key, label, default]));
    }
    pub fn add_int(&self, key: &str, label: &str, default: i64, min: i64, max: i64) {
        let _ = self.call("add_int", json!([key, label, default, min, max]));
    }
    pub fn add_float(&self, key: &str, label: &str, default: f64, min: f64, max: f64) {
        let _ = self.call("add_float", json!([key, label, default, min, max]));
    }
    pub fn add_text(&self, key: &str, label: &str, default: &str) {
        let _ = self.call("add_text", json!([key, label, default]));
    }
    pub fn add_choice(&self, key: &str, label: &str, choices: &[&str], default: &str) {
        let _ = self.call("add_choice", json!([key, label, choices, default]));
    }
    pub fn add_color(&self, key: &str, label: &str, default: &str) {
        let _ = self.call("add_color", json!([key, label, default]));
    }
    pub fn get(&self, key: &str) -> Value {
        self.call("get", json!([key])).unwrap_or(Value::Null)
    }
    pub fn get_bool(&self, key: &str) -> bool {
        self.get(key).as_bool().unwrap_or(false)
    }
    pub fn get_int(&self, key: &str) -> i64 {
        self.get(key).as_i64().unwrap_or(0)
    }
    pub fn get_float(&self, key: &str) -> f64 {
        self.get(key).as_f64().unwrap_or(0.0)
    }
    pub fn get_string(&self, key: &str) -> String {
        self.get(key).as_str().unwrap_or("").to_string()
    }
    pub fn set(&self, key: &str, value: Value) {
        let _ = self.call("set", json!([key, value]));
    }
}

fn register(callback: Callback) -> u64 {
    let id = NEXT_ID.fetch_add(1, Ordering::Relaxed);
    callbacks().lock().unwrap().insert(id, callback);
    id
}

fn host() -> &'static (HostCall, HostFree) {
    HOST.get().expect("Voktora n'a pas initialisé le plugin")
}

fn raw_call(name: &str, args: Value) -> Result<Value, String> {
    let (call, free) = host();
    let request = CString::new(json!({"name": name, "args": args}).to_string()).map_err(|e| e.to_string())?;
    let reply = call(request.as_ptr());
    if reply.is_null() {
        return Ok(Value::Null);
    }
    let text = unsafe { CStr::from_ptr(reply) }.to_string_lossy().into_owned();
    free(reply);
    let value: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    if let Some(error) = value.get("__error") {
        return Err(error.as_str().unwrap_or("erreur").to_string());
    }
    Ok(value)
}

#[doc(hidden)]
pub mod __private {
    use super::*;

    pub fn init(call: HostCall, free: HostFree) {
        let _ = HOST.set((call, free));
    }

    pub fn dispatch(request: *const c_char, on_load: fn(&Api), on_unload: fn(&Api)) -> *mut c_char {
        let text = unsafe { CStr::from_ptr(request) }.to_string_lossy().into_owned();
        let result = std::panic::catch_unwind(|| handle(&text, on_load, on_unload));
        let value = match result {
            Ok(v) => v,
            Err(panic) => {
                let message = panic
                    .downcast_ref::<&str>()
                    .map(|s| s.to_string())
                    .or_else(|| panic.downcast_ref::<String>().cloned())
                    .unwrap_or_else(|| "panique".to_string());
                json!({"error": format!("panic: {message}")})
            }
        };
        CString::new(value.to_string()).unwrap().into_raw()
    }

    fn handle(text: &str, on_load: fn(&Api), on_unload: fn(&Api)) -> Value {
        let request: Value = serde_json::from_str(text).unwrap_or(Value::Null);
        let api = Api;
        match request.get("op").and_then(Value::as_str) {
            Some("load") => {
                on_load(&api);
                json!({"ok": true})
            }
            Some("unload") => {
                on_unload(&api);
                json!({"ok": true})
            }
            Some("callback") => {
                let id = request.get("id").and_then(Value::as_u64).unwrap_or(0);
                let callback = callbacks().lock().unwrap().get(&id).cloned();
                match callback {
                    Some(cb) => {
                        let ctx = request.get("ctx").cloned().unwrap_or(Value::Null);
                        json!({"ok": true, "value": cb(&api, ctx)})
                    }
                    None => json!({"error": format!("rappel inconnu : {id}")}),
                }
            }
            _ => json!({"error": "requête inconnue"}),
        }
    }

    pub fn free(pointer: *mut c_char) {
        if !pointer.is_null() {
            unsafe { drop(CString::from_raw(pointer)) };
        }
    }
}

/// Génère les points d'entrée natifs : `plugin!(on_load, on_unload);`
#[macro_export]
macro_rules! plugin {
    ($on_load:path, $on_unload:path) => {
        #[no_mangle]
        pub extern "C" fn voktora_plugin_abi() -> u32 {
            1
        }
        #[no_mangle]
        pub extern "C" fn voktora_plugin_init(call: $crate::HostCall, free: $crate::HostFree) {
            $crate::__private::init(call, free)
        }
        #[no_mangle]
        pub extern "C" fn voktora_plugin_dispatch(request: *const ::std::ffi::c_char) -> *mut ::std::ffi::c_char {
            $crate::__private::dispatch(request, $on_load, $on_unload)
        }
        #[no_mangle]
        pub extern "C" fn voktora_plugin_free(pointer: *mut ::std::ffi::c_char) {
            $crate::__private::free(pointer)
        }
    };
}
