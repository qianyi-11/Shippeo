import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

type Point = { name: string; coord: [number, number] };

export default function RouteMap({ si, bl, color, dashed, sameRoute }: {
  si: { pol: Point; pod: Point };
  bl: { pol: Point; pod: Point };
  color: string;
  dashed?: boolean;
  sameRoute: boolean;
}) {
  const elRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const boundsRef = useRef<L.LatLngBoundsExpression | null>(null);

  // create the map once
  useEffect(() => {
    if (!elRef.current || mapRef.current) return;
    const map = L.map(elRef.current, { attributionControl: true, zoomControl: true, scrollWheelZoom: false });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);

    // Leaflet doesn't notice its container being resized on its own (e.g. the page's
    // responsive columns changing, or the window being resized) — without this the map
    // keeps rendering at its original size and the route can end up positioned outside
    // the visible tile area.
    const ro = new ResizeObserver(() => {
      map.invalidateSize();
      if (boundsRef.current) map.fitBounds(boundsRef.current, { padding: [28, 28], maxZoom: 6 });
    });
    ro.observe(elRef.current);

    return () => { ro.disconnect(); map.remove(); mapRef.current = null; layerRef.current = null; };
  }, []);

  // redraw markers/lines whenever the route data changes
  useEffect(() => {
    const map = mapRef.current, layer = layerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();

    const dot = (p: Point, c: string) =>
      L.circleMarker(p.coord, { radius: 8, color: "#ffffff", weight: 2, fillColor: c, fillOpacity: 1 })
        .bindTooltip(p.name, { permanent: true, direction: "top", offset: [0, -10], className: "route-label" });

    const bounds: L.LatLngExpression[] = [];

    if (sameRoute) {
      L.polyline([si.pol.coord, si.pod.coord], { color, weight: 3, dashArray: dashed ? "8 8" : undefined }).addTo(layer);
      dot(si.pol, color).addTo(layer); dot(si.pod, color).addTo(layer);
      bounds.push(si.pol.coord, si.pod.coord);
    } else {
      const siColor = "var(--color-norm)", blColor = "var(--color-miss)";
      L.polyline([si.pol.coord, si.pod.coord], { color: siColor, weight: 3 }).addTo(layer);
      L.polyline([bl.pol.coord, bl.pod.coord], { color: blColor, weight: 3, dashArray: "8 8" }).addTo(layer);
      dot(si.pol, siColor).addTo(layer); dot(si.pod, siColor).addTo(layer);
      dot(bl.pol, blColor).addTo(layer); dot(bl.pod, blColor).addTo(layer);
      bounds.push(si.pol.coord, si.pod.coord, bl.pol.coord, bl.pod.coord);
    }
    const llBounds = L.latLngBounds(bounds);
    boundsRef.current = llBounds;
    map.invalidateSize();
    map.fitBounds(llBounds, { padding: [28, 28], maxZoom: 6 });
  }, [si, bl, color, dashed, sameRoute]);

  return <div ref={elRef} className="h-64 w-full rounded-xl" role="img" aria-label={`Map showing the route from ${si.pol.name} to ${si.pod.name}`} />;
}
