// SPDX-License-Identifier: GPL-3.0-or-later
// Public Glycin API only. Run through harness.Worker to preserve outer isolation.
use serde_json::{Value, json};
use std::io::{Read, Write};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut input = std::io::stdin().lock();
    let mut output = std::io::stdout().lock();
    let mut image = None;
    loop {
        let mut length = [0; 4];
        input.read_exact(&mut length)?;
        let n = u32::from_be_bytes(length) as usize;
        if n == 0 || n > 65536 {
            return Err("control limit".into());
        }
        let mut data = vec![0; n];
        input.read_exact(&mut data)?;
        let request: Value = serde_json::from_slice(&data)?;
        let n = request["bytes"].as_u64().ok_or("length")? as usize;
        if n > 256 * 1024 * 1024 {
            return Err("input limit".into());
        }
        let mut data = vec![0; n];
        input.read_exact(&mut data)?;
        let mut pixels = vec![];
        let result: Result<Value, Box<dyn std::error::Error>> = (|| match request["op"].as_str() {
            Some("close") => Ok(json!({"outcome":"closed"})),
            Some("load") => {
                if std::env::var_os("GLYCIN_DISABLE_SANDBOX").is_some() {
                    return Err("sandbox override".into());
                }
                let mut loader = glycin::Loader::new_vec(data);
                loader
                    .sandbox_selector(glycin::SandboxSelector::Bwrap)
                    .accepted_memory_formats(glycin::MemoryFormatSelection::R8g8b8a8Premultiplied);
                image = Some(futures_lite::future::block_on(loader.load())?);
                Ok(json!({"outcome":"loaded"}))
            }
            Some("decode") => {
                let frame =
                    futures_lite::future::block_on(image.as_ref().ok_or("no image")?.next_frame())?;
                if frame.width() > 32768
                    || frame.height() > 32768
                    || u64::from(frame.width()) * u64::from(frame.height()) > 64000000
                    || frame.stride() != frame.width() * 4
                    || frame.buf_slice().len() > 256 * 1024 * 1024
                    || u64::from(frame.stride()) * u64::from(frame.height())
                        != frame.buf_slice().len() as u64
                {
                    return Err("layout limit".into());
                }
                pixels = frame.buf_slice().to_vec();
                let icc = frame
                    .details()
                    .color_icc_profile()
                    .map(|p| p.get_full())
                    .transpose()?;
                if icc.as_ref().is_some_and(|p| p.len() > 1024 * 1024) {
                    return Err("profile diagnostic limit".into());
                }
                Ok(
                    json!({"outcome":"success", "width":frame.width(), "height":frame.height(),
                        "stride":frame.stride(), "color_state":format!("{:?}",frame.color_state()),
                        "memory_format":format!("{:?}",frame.memory_format()), "icc_present":icc.is_some(),
                        "icc_bytes":icc.as_ref().map(|p|p.len()),
                        "icc_hex":icc.as_ref().filter(|p|p.len() <= 8192).map(|p|p.iter().map(|b|format!("{b:02x}")).collect::<String>())}),
                )
            }
            _ => Err("operation".into()),
        })();
        let mut control = result.unwrap_or_else(|e| {
            pixels.clear();
            json!({"outcome":"failure","error":e.to_string()})
        });
        control["bytes"] = json!(pixels.len());
        let control = serde_json::to_vec(&control)?;
        if control.len() > 65536 {
            return Err("response limit".into());
        }
        output.write_all(&(control.len() as u32).to_be_bytes())?;
        output.write_all(&control)?;
        output.write_all(&pixels)?;
        output.flush()?;
        if request["op"] == "close" {
            return Ok(());
        }
    }
}
