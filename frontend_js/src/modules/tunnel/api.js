import axios from "axios";

export async function fetchTunnelStatus(host) {
  const res = await axios.get(`${host}/api/tunnel/status`);
  return res.data;
}

export async function selectRandomCctv(host) {
  const res = await axios.get(`${host}/api/tunnel/select-random`);
  return res.data;
}

export async function selectCctvByName(host, name) {
  const res = await axios.get(`${host}/api/tunnel/select-cctv`, {
    params: { name },
  });
  return res.data;
}

export async function setTunnelCctvList(host, items) {
  const res = await axios.post(`${host}/api/tunnel/set-cctv-list`, {
    items,
  });
  return res.data;
}