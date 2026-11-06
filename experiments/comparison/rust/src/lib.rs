// SPDX-License-Identifier: GPL-3.0-or-later
use gio::prelude::*;
use serde_json::json;
use std::{
    panic::{AssertUnwindSafe, catch_unwind},
    ptr, slice,
};

const LIMIT: usize = 256 * 1024 * 1024;
pub struct Session {
    image: Option<glycin::Image>,
    cancel: gio::Cancellable,
    json: Vec<u8>,
    bytes: Vec<u8>,
}

fn guarded(session: &mut Session, f: impl FnOnce(&mut Session) -> Result<(), String>) -> i32 {
    match catch_unwind(AssertUnwindSafe(|| f(session))) {
        Ok(Ok(())) => 0,
        failure => {
            let error = match failure {
                Ok(Err(e)) => e,
                _ => "Rust panic contained".into(),
            };
            session.json = json!({"outcome":"failure", "error":error})
                .to_string()
                .into_bytes();
            session.bytes.clear();
            1
        }
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn comparison_new() -> *mut Session {
    catch_unwind(|| {
        Box::into_raw(Box::new(Session {
            image: None,
            cancel: gio::Cancellable::new(),
            json: vec![],
            bytes: vec![],
        }))
    })
    .unwrap_or(ptr::null_mut())
}

// All session calls require exclusive access, including cancel. Pointers are private
// to the C++ worker. Active-operation termination belongs to the parent process scope.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn comparison_load(
    s: *mut Session,
    data: *const u8,
    length: usize,
    capsule: bool,
    ignore: bool,
) -> i32 {
    let Some(s) = (unsafe { s.as_mut() }) else {
        return -1;
    };
    guarded(s, |s| {
        if length > LIMIT || (length != 0 && data.is_null()) {
            return Err("input limit".into());
        }
        if std::env::var_os("GLYCIN_DISABLE_SANDBOX").is_some() {
            return Err("sandbox override".into());
        }
        let bytes = if length == 0 {
            vec![]
        } else {
            unsafe { slice::from_raw_parts(data, length) }.to_vec()
        };
        s.image = None;
        s.cancel = gio::Cancellable::new();
        let mut loader = if capsule {
            glycin::Loader::new(gio::File::for_path("/capsule/main.svg"))
        } else {
            glycin::Loader::new_vec(bytes)
        };
        loader
            .sandbox_selector(glycin::SandboxSelector::Bwrap)
            .accepted_memory_formats(glycin::MemoryFormatSelection::R8g8b8a8Premultiplied)
            .use_expose_base_dir(capsule)
            .apply_transformations(!ignore)
            .cancellable(s.cancel.clone());
        let image = futures_lite::future::block_on(loader.load()).map_err(|e| e.to_string())?;
        let details = image.details();
        if details.width() == 0
            || details.height() == 0
            || details.width() > 32768
            || details.height() > 32768
            || u64::from(details.width()) * u64::from(details.height()) > 64000000
        {
            return Err("source dimensions".into());
        }
        s.bytes = match details.metadata_exif() {
            Some(exif) => exif.get_full().map_err(|e| e.to_string())?,
            None => vec![],
        };
        if s.bytes.len() > 1024 * 1024 {
            return Err("metadata limit".into());
        }
        let orientation = image.transformation_orientation() as u16;
        let (mut stored_width, mut stored_height) = (details.width(), details.height());
        if !ignore && orientation >= 5 {
            std::mem::swap(&mut stored_width, &mut stored_height);
        }
        s.json = json!({"source_width":stored_width, "source_height":stored_height,
                        "orientation":orientation, "orientation_policy":if ignore { "Ignore" } else { "Apply" },
                        "outcome":"loaded", "oriented_width":details.width(), "oriented_height":details.height(),
                        "exif_bytes":s.bytes.len(), "metadata":details.metadata_key_value(),
                        "protocol":glycin::COMPAT_VERSION, "sandbox":format!("{:?}", image.active_sandbox_mechanism())})
            .to_string().into_bytes();
        s.image = Some(image);
        Ok(())
    })
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn comparison_frame(s: *mut Session, width: u32, height: u32) -> i32 {
    let Some(s) = (unsafe { s.as_mut() }) else {
        return -1;
    };
    guarded(s, |s| {
        if width == 0 || height == 0 || width > 32768 || height > 32768 {
            return Err("bound".into());
        }
        let image = s.image.as_ref().ok_or("no session")?;
        let frame = match futures_lite::future::block_on(
            image.specific_frame(
                glycin::FrameRequest::new()
                    .scale(width, height)
                    .loop_animation(false),
            ),
        ) {
            Ok(frame) => frame,
            Err(error) if error.is_no_more_frames() => {
                s.json = json!({"outcome":"end"}).to_string().into_bytes();
                s.bytes.clear();
                return Ok(());
            }
            Err(error) => return Err(error.to_string()),
        };
        let bytes = frame.buf_slice();
        if frame.width() == 0
            || frame.height() == 0
            || frame.width() > 32768
            || frame.height() > 32768
            || u64::from(frame.width()) * u64::from(frame.height()) > 64000000
            || bytes.len() > LIMIT
            || u64::from(frame.stride()) * u64::from(frame.height()) != bytes.len() as u64
        {
            return Err("invalid frame layout".into());
        }
        s.bytes = bytes.to_vec();
        s.json = json!({"outcome":"success", "width":frame.width(), "height":frame.height(),
                        "stride":frame.stride(), "bytes":s.bytes.len(),
                        "icc_present":frame.details().color_icc_profile().is_some(),
                        "memory_format":format!("{:?}",frame.memory_format()),
                        "color_state":format!("{:?}",frame.color_state()),
                        "delay_us":frame.delay().map(|v| v.as_micros() as u64)})
        .to_string()
        .into_bytes();
        Ok(())
    })
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn comparison_result(
    s: *const Session,
    length: *mut usize,
    pixels: bool,
) -> *const u8 {
    let Some(s) = (unsafe { s.as_ref() }) else {
        return ptr::null();
    };
    if length.is_null() {
        return ptr::null();
    }
    let bytes = if pixels { &s.bytes } else { &s.json };
    unsafe { *length = bytes.len() };
    bytes.as_ptr()
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn comparison_cancel(s: *const Session) {
    let _ = catch_unwind(AssertUnwindSafe(|| {
        if let Some(s) = unsafe { s.as_ref() } {
            s.cancel.cancel();
        }
    }));
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn comparison_free(s: *mut Session) {
    let _ = catch_unwind(AssertUnwindSafe(|| {
        if !s.is_null() {
            drop(unsafe { Box::from_raw(s) });
        }
    }));
}

// Private configuration discovery only: never execute the configured loader.
#[unsafe(no_mangle)]
pub extern "C" fn comparison_config() -> *mut std::ffi::c_char {
    catch_unwind(|| {
        let config = futures_lite::future::block_on(glycin::config::Config::cached());
        let mime = glycin::config::MimeType::new_static("image/x-holonight-runtime-control");
        let selected = config
            .loader(&mime)
            .map(|entry| entry.exec.to_string_lossy().into_owned())
            .unwrap_or_default();
        std::ffi::CString::new(selected)
            .map(|value| value.into_raw())
            .unwrap_or(ptr::null_mut())
    })
    .unwrap_or(ptr::null_mut())
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn comparison_config_free(value: *mut std::ffi::c_char) {
    if !value.is_null() {
        drop(unsafe { std::ffi::CString::from_raw(value) });
    }
}
