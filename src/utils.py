import os
import json
import requests
import networkx as nx
from typing import Dict, Tuple

Graph = nx.MultiDiGraph
CacheDict = Dict[Tuple[int, int], float]
class OSRMDistanceProvider:
    """
    Calculates distances by querying a local OSRM server.
    It keeps an in-memory cache to avoid repeated API calls for the same pair.
    """
    def __init__(self, graph: Graph, host: str = 'http://127.0.0.1:5000'):
        self.host = host
        self.node_coords = self._extract_node_coords(graph)
        self._cache: Dict[Tuple[int, int], float] = {}
        print(f"OSRM Mesafe Sağlayıcı başlatıldı. Sunucu: {self.host}")

    def _extract_node_coords(self, graph: Graph) -> Dict[int, Tuple[float, float]]:
        """Extracts longitude and latitude for each node from the graph."""
        coords = {}
        for node, data in graph.nodes(data=True):
            coords[node] = (data['x'], data['y'])
        return coords

    def get_distance(self, u_node: int, v_node: int) -> float:
        """
        Gets the driving distance in meters between two nodes.
        First checks the local cache, then queries the OSRM server if not found.
        """
        if u_node == v_node:
            return 0.0

        edge = tuple(sorted((u_node, v_node)))
        if edge in self._cache:
            return self._cache[edge]

        try:
            lon1, lat1 = self.node_coords[u_node]
            lon2, lat2 = self.node_coords[v_node]
        except KeyError as e:
            print(f"HATA: Düğüm ID'si {e} için koordinat bulunamadı.")
            return float('inf')

        url = f"{self.host}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data['code'] == 'Ok' and data.get('routes'):
                distance_meters = data['routes'][0]['distance']
                self._cache[edge] = distance_meters
                return distance_meters
            else:
                print(f"UYARI: OSRM {u_node} ve {v_node} arasında rota bulamadı. Cevap: {data.get('code')}")
                self._cache[edge] = float('inf')
                return float('inf')

        except requests.exceptions.RequestException as e:
            print(f"KRİTİK HATA: OSRM sunucusuna bağlanılamadı ({self.host}). Docker container'ının çalıştığından emin olun. Hata: {e}")
            return float('inf')

    def save_to_disk(self):
        """
        This method exists for compatibility with the optimizer's call.
        The OSRM cache is in-memory and not saved by default.
        """
        print(f"OSRM oturum önbelleğinde {len(self._cache)} adet mesafe biriktirildi.")

class DistanceCache:
    """
    Manages a two-level cache for node-to-node distances to speed up
    repeated shortest_path calculations.
    """
    def __init__(self, graph: Graph, cache_filepath: str = "data/cache/distance_cache.json"):
        print("Mesafe önbelleği (DistanceCache) başlatılıyor...")
        self.graph = graph
        self.cache_filepath = cache_filepath
        self.memory_cache: CacheDict = {}
        self.load_from_disk()

    def get_distance(self, u: int, v: int) -> float:
        if u == v:
            return 0.0
        edge = tuple(sorted((u, v)))
        if edge in self.memory_cache:
            return self.memory_cache[edge]
        try:
            distance = nx.shortest_path_length(self.graph, u, v, weight='length')
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            distance = float('inf')
        self.memory_cache[edge] = distance
        return distance

    def load_from_disk(self) -> None:
        if os.path.exists(self.cache_filepath) and os.path.getsize(self.cache_filepath) > 0:
            print(f"'{self.cache_filepath}' adresinden kalıcı önbellek yükleniyor...")
            try:
                with open(self.cache_filepath, 'r') as f:
                    str_key_cache: Dict[str, float] = json.load(f)
                    self.memory_cache = {eval(key): value for key, value in str_key_cache.items()}
                print(f"{len(self.memory_cache)} adet mesafe önbellekten yüklendi.")
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Önbellek dosyası okunurken hata oluştu: {e}. Boş bir önbellek ile devam ediliyor.")
                self.memory_cache = {}
        else:
            print("Kalıcı önbellek dosyası bulunamadı veya boş. Yeni bir önbellek oluşturulacak.")
            self.memory_cache = {}

    def save_to_disk(self) -> None:
        print(f"Güncel mesafe önbelleği '{self.cache_filepath}' adresine kaydediliyor...")
        str_key_cache = {str(key): value for key, value in self.memory_cache.items()}
        os.makedirs(os.path.dirname(self.cache_filepath), exist_ok=True)
        with open(self.cache_filepath, 'w') as f:
            json.dump(str_key_cache, f, indent=4)
        print(f"{len(str_key_cache)} adet mesafe başarıyla kalıcı önbelleğe kaydedildi.")
    
def update_config_with_args(config: dict, args) -> dict:
    arg_to_config_map = {
        'strategy': ('problem', 'strategy'),
        'num_stops': ('problem', 'num_stops'),
        'scenario': ('problem', 'scenario_filepath'),
        'ants': ('aco', 'ant_count'),
        'iterations': ('aco', 'iterations'),
        'output': ('output', 'map_filename'),
    }
    for arg_name, config_keys in arg_to_config_map.items():
        arg_value = getattr(args, arg_name, None)
        if arg_value is not None:
            temp_dict = config
            for key in config_keys[:-1]:
                temp_dict = temp_dict[key]
            temp_dict[config_keys[-1]] = arg_value
            print(f"Yapılandırma güncellendi: '{'.'.join(config_keys)}' -> {arg_value}")
    return config