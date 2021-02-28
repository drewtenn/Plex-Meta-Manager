import logging, os, re, requests
from modules import util
from modules.anidb import AniDBAPI
from modules.builder import CollectionBuilder
from modules.cache import Cache
from modules.imdb import IMDbAPI
from modules.mal import MyAnimeListAPI
from modules.mal import MyAnimeListIDList
from modules.plex import PlexAPI
from modules.radarr import RadarrAPI
from modules.sonarr import SonarrAPI
from modules.tautulli import TautulliAPI
from modules.tmdb import TMDbAPI
from modules.trakttv import TraktAPI
from modules.tvdb import TVDbAPI
from modules.util import Failed
from plexapi.exceptions import BadRequest
from ruamel import yaml

logger = logging.getLogger("Plex Meta Manager")

class Config:
    def __init__(self, default_dir, config_path=None):
        logger.info("Locating config...")
        if config_path and os.path.exists(config_path):                     self.config_path = os.path.abspath(config_path)
        elif config_path and not os.path.exists(config_path):               raise Failed(f"Config Error: config not found at {os.path.abspath(config_path)}")
        elif os.path.exists(os.path.join(default_dir, "config.yml")):       self.config_path = os.path.abspath(os.path.join(default_dir, "config.yml"))
        else:                                                               raise Failed(f"Config Error: config not found at {os.path.abspath(default_dir)}")
        logger.info(f"Using {self.config_path} as config")

        yaml.YAML().allow_duplicate_keys = True
        try:
            new_config, ind, bsi = yaml.util.load_yaml_guess_indent(open(self.config_path))
            def replace_attr(all_data, attr, par):
                if "settings" not in all_data:
                    all_data["settings"] = {}
                if par in all_data and all_data[par] and attr in all_data[par] and attr not in all_data["settings"]:
                    all_data["settings"][attr] = all_data[par][attr]
                    del all_data[par][attr]
            if "libraries" not in new_config:
                new_config["libraries"] = {}
            if "settings" not in new_config:
                new_config["settings"] = {}
            if "tmdb" not in new_config:
                new_config["tmdb"] = {}
            replace_attr(new_config, "cache", "cache")
            replace_attr(new_config, "cache_expiration", "cache")
            if "config" in new_config:
                del new_config["cache"]
            replace_attr(new_config, "asset_directory", "plex")
            replace_attr(new_config, "sync_mode", "plex")
            replace_attr(new_config, "show_unmanaged", "plex")
            replace_attr(new_config, "show_filtered", "plex")
            replace_attr(new_config, "show_missing", "plex")
            replace_attr(new_config, "save_missing", "plex")
            if new_config["libraries"]:
                for library in new_config["libraries"]:
                    if "plex" in new_config["libraries"][library]:
                        replace_attr(new_config["libraries"][library], "asset_directory", "plex")
                        replace_attr(new_config["libraries"][library], "sync_mode", "plex")
                        replace_attr(new_config["libraries"][library], "show_unmanaged", "plex")
                        replace_attr(new_config["libraries"][library], "show_filtered", "plex")
                        replace_attr(new_config["libraries"][library], "show_missing", "plex")
                        replace_attr(new_config["libraries"][library], "save_missing", "plex")
            if "libraries" in new_config:                   new_config["libraries"] = new_config.pop("libraries")
            if "settings" in new_config:                    new_config["settings"] = new_config.pop("settings")
            if "plex" in new_config:                        new_config["plex"] = new_config.pop("plex")
            if "tmdb" in new_config:                        new_config["tmdb"] = new_config.pop("tmdb")
            if "tautulli" in new_config:                    new_config["tautulli"] = new_config.pop("tautulli")
            if "radarr" in new_config:                      new_config["radarr"] = new_config.pop("radarr")
            if "sonarr" in new_config:                      new_config["sonarr"] = new_config.pop("sonarr")
            if "trakt" in new_config:                       new_config["trakt"] = new_config.pop("trakt")
            if "mal" in new_config:                         new_config["mal"] = new_config.pop("mal")
            yaml.round_trip_dump(new_config, open(self.config_path, "w"), indent=ind, block_seq_indent=bsi)
            self.data = new_config
        except yaml.scanner.ScannerError as e:
            raise Failed(f"YAML Error: {util.tab_new_lines(e)}")

        def check_for_attribute(data, attribute, parent=None, test_list=None, options="", default=None, do_print=True, default_is_none=False, req_default=False, var_type="str", throw=False, save=True):
            endline = ""
            if parent is not None:
                if parent in data:
                    data = data[parent]
                else:
                    data = None
                    do_print = False
                    save = False
            text = f"{attribute} attribute" if parent is None else f"{parent} sub-attribute {attribute}"
            if data is None or attribute not in data:
                message = f"{text} not found"
                if parent and save is True:
                    loaded_config, ind_in, bsi_in = yaml.util.load_yaml_guess_indent(open(self.config_path))
                    endline = f"\n{parent} sub-attribute {attribute} added to config"
                    if parent not in loaded_config or not loaded_config[parent]:        loaded_config[parent] = {attribute: default}
                    elif attribute not in loaded_config[parent]:                        loaded_config[parent][attribute] = default
                    else:                                                               endline = ""
                    yaml.round_trip_dump(loaded_config, open(self.config_path, "w"), indent=ind_in, block_seq_indent=bsi_in)
            elif not data[attribute] and data[attribute] is not False:
                if default_is_none is True:                                         return None
                else:                                                               message = f"{text} is blank"
            elif var_type == "bool":
                if isinstance(data[attribute], bool):                               return data[attribute]
                else:                                                               message = f"{text} must be either true or false"
            elif var_type == "int":
                if isinstance(data[attribute], int) and data[attribute] > 0:        return data[attribute]
                else:                                                               message = f"{text} must an integer > 0"
            elif var_type == "path":
                if os.path.exists(os.path.abspath(data[attribute])):                return data[attribute]
                else:                                                               message = f"Path {os.path.abspath(data[attribute])} does not exist"
            elif var_type == "list":                                            return util.get_list(data[attribute])
            elif var_type == "list_path":
                temp_list = [path for path in util.get_list(data[attribute], split=True) if os.path.exists(os.path.abspath(path))]
                if len(temp_list) > 0:                                              return temp_list
                else:                                                               message = "No Paths exist"
            elif var_type == "lower_list":                                      return util.get_list(data[attribute], lower=True)
            elif test_list is None or data[attribute] in test_list:             return data[attribute]
            else:                                                               message = f"{text}: {data[attribute]} is an invalid input"
            if var_type == "path" and default and os.path.exists(os.path.abspath(default)):
                return default
            elif var_type == "path" and default:
                default = None
                if attribute in data and data[attribute]:
                    message = f"neither {data[attribute]} or the default path {default} could be found"
                else:
                    message = f"no {text} found and the default path {default} could be found"
            if default is not None or default_is_none:
                message = message + f" using {default} as default"
            message = message + endline
            if req_default and default is None:
                raise Failed(f"Config Error: {attribute} attribute must be set under {parent} globally or under this specific Library")
            if (default is None and not default_is_none) or throw:
                if len(options) > 0:
                    message = message + "\n" + options
                raise Failed(f"Config Error: {message}")
            if do_print:
                util.print_multiline(f"Config Warning: {message}")
                if attribute in data and data[attribute] and test_list is not None and data[attribute] not in test_list:
                    util.print_multiline(options)
            return default

        self.general = {}
        self.general["cache"] = check_for_attribute(self.data, "cache", parent="settings", options="    true (Create a cache to store ids)\n    false (Do not create a cache to store ids)", var_type="bool", default=True)
        self.general["cache_expiration"] = check_for_attribute(self.data, "cache_expiration", parent="settings", var_type="int", default=60)
        if self.general["cache"]:
            util.separator()
            self.Cache = Cache(self.config_path, self.general["cache_expiration"])
        else:
            self.Cache = None
        self.general["asset_directory"] = check_for_attribute(self.data, "asset_directory", parent="settings", var_type="list_path", default=[os.path.join(default_dir, "assets")])
        self.general["sync_mode"] = check_for_attribute(self.data, "sync_mode", parent="settings", default="append", test_list=["append", "sync"], options="    append (Only Add Items to the Collection)\n    sync (Add & Remove Items from the Collection)")
        self.general["show_unmanaged"] = check_for_attribute(self.data, "show_unmanaged", parent="settings", var_type="bool", default=True)
        self.general["show_filtered"] = check_for_attribute(self.data, "show_filtered", parent="settings", var_type="bool", default=False)
        self.general["show_missing"] = check_for_attribute(self.data, "show_missing", parent="settings", var_type="bool", default=True)
        self.general["save_missing"] = check_for_attribute(self.data, "save_missing", parent="settings", var_type="bool", default=True)

        util.separator()

        self.TMDb = None
        if "tmdb" in self.data:
            logger.info("Connecting to TMDb...")
            self.tmdb = {}
            try:                                self.tmdb["apikey"] = check_for_attribute(self.data, "apikey", parent="tmdb", throw=True)
            except Failed as e:                 raise Failed(e)
            self.tmdb["language"] = check_for_attribute(self.data, "language", parent="tmdb", default="en")
            self.TMDb = TMDbAPI(self.tmdb)
            logger.info(f"TMDb Connection {'Failed' if self.TMDb is None else 'Successful'}")
        else:
            raise Failed("Config Error: tmdb attribute not found")

        util.separator()

        self.Trakt = None
        if "trakt" in self.data:
            logger.info("Connecting to Trakt...")
            self.trakt = {}
            try:
                self.trakt["client_id"] = check_for_attribute(self.data, "client_id", parent="trakt", throw=True)
                self.trakt["client_secret"] = check_for_attribute(self.data, "client_secret", parent="trakt", throw=True)
                self.trakt["config_path"] = self.config_path
                authorization = self.data["trakt"]["authorization"] if "authorization" in self.data["trakt"] and self.data["trakt"]["authorization"] else None
                self.Trakt = TraktAPI(self.trakt, authorization)
            except Failed as e:
                logger.error(e)
            logger.info(f"Trakt Connection {'Failed' if self.Trakt is None else 'Successful'}")
        else:
            logger.warning("trakt attribute not found")

        util.separator()

        self.MyAnimeList = None
        self.MyAnimeListIDList = MyAnimeListIDList()
        if "mal" in self.data:
            logger.info("Connecting to My Anime List...")
            self.mal = {}
            try:
                self.mal["client_id"] = check_for_attribute(self.data, "client_id", parent="mal", throw=True)
                self.mal["client_secret"] = check_for_attribute(self.data, "client_secret", parent="mal", throw=True)
                self.mal["config_path"] = self.config_path
                authorization = self.data["mal"]["authorization"] if "authorization" in self.data["mal"] and self.data["mal"]["authorization"] else None
                self.MyAnimeList = MyAnimeListAPI(self.mal, self.MyAnimeListIDList, authorization)
            except Failed as e:
                logger.error(e)
            logger.info(f"My Anime List Connection {'Failed' if self.MyAnimeList is None else 'Successful'}")
        else:
            logger.warning("mal attribute not found")

        self.TVDb = TVDbAPI(Cache=self.Cache, TMDb=self.TMDb, Trakt=self.Trakt)
        self.IMDb = IMDbAPI(Cache=self.Cache, TMDb=self.TMDb, Trakt=self.Trakt, TVDb=self.TVDb) if self.TMDb or self.Trakt else None
        self.AniDB = AniDBAPI(Cache=self.Cache, TMDb=self.TMDb, Trakt=self.Trakt)

        util.separator()

        logger.info("Connecting to Plex Libraries...")

        self.general["plex"] = {}
        self.general["plex"]["url"] = check_for_attribute(self.data, "url", parent="plex", default_is_none=True)
        self.general["plex"]["token"] = check_for_attribute(self.data, "token", parent="plex", default_is_none=True)
        self.general["plex"]["timeout"] = check_for_attribute(self.data, "timeout", parent="plex", var_type="int", default=60)

        self.general["radarr"] = {}
        self.general["radarr"]["url"] = check_for_attribute(self.data, "url", parent="radarr", default_is_none=True)
        self.general["radarr"]["version"] = check_for_attribute(self.data, "version", parent="radarr", test_list=["v2", "v3"], options="    v2 (For Radarr 0.2)\n    v3 (For Radarr 3.0)", default="v2")
        self.general["radarr"]["token"] = check_for_attribute(self.data, "token", parent="radarr", default_is_none=True)
        self.general["radarr"]["quality_profile"] = check_for_attribute(self.data, "quality_profile", parent="radarr", default_is_none=True)
        self.general["radarr"]["root_folder_path"] = check_for_attribute(self.data, "root_folder_path", parent="radarr", default_is_none=True)
        self.general["radarr"]["add"] = check_for_attribute(self.data, "add", parent="radarr", var_type="bool", default=False)
        self.general["radarr"]["search"] = check_for_attribute(self.data, "search", parent="radarr", var_type="bool", default=False)
        self.general["radarr"]["tag"] = check_for_attribute(self.data, "tag", parent="radarr", var_type="lower_list", default_is_none=True)

        self.general["sonarr"] = {}
        self.general["sonarr"]["url"] = check_for_attribute(self.data, "url", parent="sonarr", default_is_none=True)
        self.general["sonarr"]["token"] = check_for_attribute(self.data, "token", parent="sonarr", default_is_none=True)
        self.general["sonarr"]["version"] = check_for_attribute(self.data, "version", parent="sonarr", test_list=["v2", "v3"], options="    v2 (For Sonarr 0.2)\n    v3 (For Sonarr 3.0)", default="v2")
        self.general["sonarr"]["quality_profile"] = check_for_attribute(self.data, "quality_profile", parent="sonarr", default_is_none=True)
        self.general["sonarr"]["root_folder_path"] = check_for_attribute(self.data, "root_folder_path", parent="sonarr", default_is_none=True)
        self.general["sonarr"]["add"] = check_for_attribute(self.data, "add", parent="sonarr", var_type="bool", default=False)
        self.general["sonarr"]["search"] = check_for_attribute(self.data, "search", parent="sonarr", var_type="bool", default=False)
        self.general["sonarr"]["tag"] = check_for_attribute(self.data, "tag", parent="sonarr", var_type="lower_list", default_is_none=True)

        self.general["tautulli"] = {}
        self.general["tautulli"]["url"] = check_for_attribute(self.data, "url", parent="tautulli", default_is_none=True)
        self.general["tautulli"]["apikey"] = check_for_attribute(self.data, "apikey", parent="tautulli", default_is_none=True)

        self.libraries = []
        try:                            libs = check_for_attribute(self.data, "libraries", throw=True)
        except Failed as e:             raise Failed(e)
        for lib in libs:
            util.separator()
            params = {}
            if "library_name" in libs[lib] and libs[lib]["library_name"]:
                params["name"] = str(libs[lib]["library_name"])
                logger.info(f"Connecting to {params['name']} ({lib}) Library...")
            else:
                params["name"] = str(lib)
                logger.info(f"Connecting to {params['name']} Library...")

            params["asset_directory"] = check_for_attribute(libs[lib], "asset_directory", parent="settings", var_type="list_path", default=self.general["asset_directory"], default_is_none=True, save=False)
            if params["asset_directory"] is None:
                logger.warning("Config Warning: Assets will not be used asset_directory attribute must be set under config or under this specific Library")

            params["sync_mode"] = check_for_attribute(libs[lib], "sync_mode", parent="settings", test_list=["append", "sync"], options="    append (Only Add Items to the Collection)\n    sync (Add & Remove Items from the Collection)", default=self.general["sync_mode"], save=False)
            params["show_unmanaged"] = check_for_attribute(libs[lib], "show_unmanaged", parent="settings", var_type="bool", default=self.general["show_unmanaged"], save=False)
            params["show_filtered"] = check_for_attribute(libs[lib], "show_filtered", parent="settings", var_type="bool", default=self.general["show_filtered"], save=False)
            params["show_missing"] = check_for_attribute(libs[lib], "show_missing", parent="settings", var_type="bool", default=self.general["show_missing"], save=False)
            params["save_missing"] = check_for_attribute(libs[lib], "save_missing", parent="settings", var_type="bool", default=self.general["save_missing"], save=False)

            try:
                params["metadata_path"] = check_for_attribute(libs[lib], "metadata_path", var_type="path", default=os.path.join(default_dir, f"{lib}.yml"), throw=True)
                params["library_type"] = check_for_attribute(libs[lib], "library_type", test_list=["movie", "show"], options="    movie (For Movie Libraries)\n    show (For Show Libraries)", throw=True)
                params["plex"] = {}
                params["plex"]["url"] = check_for_attribute(libs[lib], "url", parent="plex", default=self.general["plex"]["url"], req_default=True, save=False)
                params["plex"]["token"] = check_for_attribute(libs[lib], "token", parent="plex", default=self.general["plex"]["token"], req_default=True, save=False)
                params["plex"]["timeout"] = check_for_attribute(libs[lib], "timeout", parent="plex", var_type="int", default=self.general["plex"]["timeout"], save=False)
                library = PlexAPI(params, self.TMDb, self.TVDb)
                logger.info(f"{params['name']} Library Connection Successful")
            except Failed as e:
                util.print_multiline(e)
                logger.info(f"{params['name']} Library Connection Failed")
                continue

            if self.general["radarr"]["url"] or "radarr" in libs[lib]:
                logger.info(f"Connecting to {params['name']} library's Radarr...")
                radarr_params = {}
                try:
                    radarr_params["url"] = check_for_attribute(libs[lib], "url", parent="radarr", default=self.general["radarr"]["url"], req_default=True, save=False)
                    radarr_params["token"] = check_for_attribute(libs[lib], "token", parent="radarr", default=self.general["radarr"]["token"], req_default=True, save=False)
                    radarr_params["version"] = check_for_attribute(libs[lib], "version", parent="radarr", test_list=["v2", "v3"], options="    v2 (For Radarr 0.2)\n    v3 (For Radarr 3.0)", default=self.general["radarr"]["version"], save=False)
                    radarr_params["quality_profile"] = check_for_attribute(libs[lib], "quality_profile", parent="radarr", default=self.general["radarr"]["quality_profile"], req_default=True, save=False)
                    radarr_params["root_folder_path"] = check_for_attribute(libs[lib], "root_folder_path", parent="radarr", default=self.general["radarr"]["root_folder_path"], req_default=True, save=False)
                    radarr_params["add"] = check_for_attribute(libs[lib], "add", parent="radarr", var_type="bool", default=self.general["radarr"]["add"], save=False)
                    radarr_params["search"] = check_for_attribute(libs[lib], "search", parent="radarr", var_type="bool", default=self.general["radarr"]["search"], save=False)
                    radarr_params["tag"] = check_for_attribute(libs[lib], "search", parent="radarr", var_type="lower_list", default=self.general["radarr"]["tag"], default_is_none=True, save=False)
                    library.add_Radarr(RadarrAPI(self.TMDb, radarr_params))
                except Failed as e:
                    util.print_multiline(e)
                logger.info(f"{params['name']} library's Radarr Connection {'Failed' if library.Radarr is None else 'Successful'}")

            if self.general["sonarr"]["url"] or "sonarr" in libs[lib]:
                logger.info(f"Connecting to {params['name']} library's Sonarr...")
                sonarr_params = {}
                try:
                    sonarr_params["url"] = check_for_attribute(libs[lib], "url", parent="sonarr", default=self.general["sonarr"]["url"], req_default=True, save=False)
                    sonarr_params["token"] = check_for_attribute(libs[lib], "token", parent="sonarr", default=self.general["sonarr"]["token"], req_default=True, save=False)
                    sonarr_params["version"] = check_for_attribute(libs[lib], "version", parent="sonarr", test_list=["v2", "v3"], options="    v2 (For Sonarr 0.2)\n    v3 (For Sonarr 3.0)", default=self.general["sonarr"]["version"], save=False)
                    sonarr_params["quality_profile"] = check_for_attribute(libs[lib], "quality_profile", parent="sonarr", default=self.general["sonarr"]["quality_profile"], req_default=True, save=False)
                    sonarr_params["root_folder_path"] = check_for_attribute(libs[lib], "root_folder_path", parent="sonarr", default=self.general["sonarr"]["root_folder_path"], req_default=True, save=False)
                    sonarr_params["add"] = check_for_attribute(libs[lib], "add", parent="sonarr", var_type="bool", default=self.general["sonarr"]["add"], save=False)
                    sonarr_params["search"] = check_for_attribute(libs[lib], "search", parent="sonarr", var_type="bool", default=self.general["sonarr"]["search"], save=False)
                    sonarr_params["tag"] = check_for_attribute(libs[lib], "search", parent="sonarr", var_type="lower_list", default=self.general["sonarr"]["tag"], default_is_none=True, save=False)
                    library.add_Sonarr(SonarrAPI(self.TVDb, sonarr_params, library.Plex.language))
                except Failed as e:
                    util.print_multiline(e)
                logger.info(f"{params['name']} library's Sonarr Connection {'Failed' if library.Sonarr is None else 'Successful'}")

            if self.general["tautulli"]["url"] or "tautulli" in libs[lib]:
                logger.info(f"Connecting to {params['name']} library's Tautulli...")
                tautulli_params = {}
                try:
                    tautulli_params["url"] = check_for_attribute(libs[lib], "url", parent="tautulli", default=self.general["tautulli"]["url"], req_default=True, save=False)
                    tautulli_params["apikey"] = check_for_attribute(libs[lib], "apikey", parent="tautulli", default=self.general["tautulli"]["apikey"], req_default=True, save=False)
                    library.add_Tautulli(TautulliAPI(tautulli_params))
                except Failed as e:
                    util.print_multiline(e)
                logger.info(f"{params['name']} library's Tautulli Connection {'Failed' if library.Tautulli is None else 'Successful'}")

            self.libraries.append(library)

        util.separator()

        if len(self.libraries) > 0:
            logger.info(f"{len(self.libraries)} Plex Library Connection{'s' if len(self.libraries) > 1 else ''} Successful")
        else:
            raise Failed("Plex Error: No Plex libraries were found")

        util.separator()

    def update_libraries(self, test, requested_collections):
        for library in self.libraries:
            os.environ["PLEXAPI_PLEXAPI_TIMEOUT"] = str(library.timeout)
            logger.info("")
            util.separator(f"{library.name} Library")
            try:                        library.update_metadata(self.TMDb, test)
            except Failed as e:         logger.error(e)
            logger.info("")
            util.separator(f"{library.name} Library {'Test ' if test else ''}Collections")
            collections = {c: library.collections[c] for c in util.get_list(requested_collections) if c in library.collections} if requested_collections else library.collections
            if collections:
                logger.info("")
                util.separator(f"Mapping {library.name} Library")
                logger.info("")
                movie_map, show_map = self.map_guids(library)
                for c in collections:
                    if test and ("test" not in collections[c] or collections[c]["test"] is not True):
                        no_template_test = True
                        if "template" in collections[c] and collections[c]["template"]:
                            for data_template in util.get_list(collections[c]["template"], split=False):
                                if "name" in data_template \
                                    and data_template["name"] \
                                    and library.templates \
                                    and data_template["name"] in library.templates \
                                    and library.templates[data_template["name"]] \
                                    and "test" in library.templates[data_template["name"]] \
                                    and library.templates[data_template["name"]]["test"] is True:
                                    no_template_test = False
                        if no_template_test:
                            continue
                    try:
                        logger.info("")
                        util.separator(f"{c} Collection")
                        logger.info("")

                        rating_key_map = {}
                        try:
                            builder = CollectionBuilder(self, library, c, collections[c])
                        except Failed as ef:
                            util.print_multiline(ef, error=True)
                            continue
                        except Exception as ee:
                            util.print_stacktrace()
                            logger.error(ee)
                            continue

                        try:
                            collection_obj = library.get_collection(c)
                            collection_name = collection_obj.title
                        except Failed:
                            collection_obj = None
                            collection_name = c

                        if len(builder.schedule) > 0:
                            util.print_multiline(builder.schedule, info=True)

                        logger.info("")
                        if builder.sync:
                            logger.info("Sync Mode: sync")
                            if collection_obj:
                                for item in collection_obj.items():
                                    rating_key_map[item.ratingKey] = item
                        else:
                            logger.info("Sync Mode: append")

                        for i, f in enumerate(builder.filters):
                            if i == 0:
                                logger.info("")
                            logger.info(f"Collection Filter {f[0]}: {f[1]}")

                        builder.run_methods(collection_obj, collection_name, rating_key_map, movie_map, show_map)

                        try:
                            plex_collection = library.get_collection(collection_name)
                        except Failed as e:
                            logger.debug(e)
                            continue

                        builder.update_details(plex_collection)

                    except Exception as e:
                        util.print_stacktrace()
                        logger.error(f"Unknown Error: {e}")
                if library.show_unmanaged is True and not test and not requested_collections:
                    logger.info("")
                    util.separator(f"Unmanaged Collections in {library.name} Library")
                    logger.info("")
                    unmanaged_count = 0
                    collections_in_plex = [str(plex_col) for plex_col in collections]
                    for col in library.get_all_collections():
                        if col.title not in collections_in_plex:
                            logger.info(col.title)
                            unmanaged_count += 1
                    logger.info("{} Unmanaged Collections".format(unmanaged_count))
            else:
                logger.info("")
                logger.error("No collection to update")

    def map_guids(self, library):
        movie_map = {}
        show_map = {}
        length = 0
        logger.info(f"Mapping {'Movie' if library.is_movie else 'Show'} Library: {library.name}")
        items = library.Plex.all()
        for i, item in enumerate(items, 1):
            length = util.print_return(length, f"Processing: {i}/{len(items)} {item.title}")
            try:
                id_type, main_id = self.get_id(item, library, length)
            except BadRequest:
                util.print_stacktrace()
                util.print_end(length, f"{'Cache | ! |' if self.Cache else 'Mapping Error:'} | {item.guid} for {item.title} not found")
                continue
            if isinstance(main_id, list):
                if id_type == "movie":
                    for m in main_id:                               movie_map[m] = item.ratingKey
                elif id_type == "show":
                    for m in main_id:                               show_map[m] = item.ratingKey
            else:
                if id_type == "movie":                          movie_map[main_id] = item.ratingKey
                elif id_type == "show":                         show_map[main_id] = item.ratingKey
        util.print_end(length, f"Processed {len(items)} {'Movies' if library.is_movie else 'Shows'}")
        return movie_map, show_map

    def get_id(self, item, library, length):
        expired = None
        tmdb_id = None
        imdb_id = None
        tvdb_id = None
        anidb_id = None
        mal_id = None
        error_message = None
        if self.Cache:
            if library.is_movie:                            tmdb_id, expired = self.Cache.get_tmdb_id("movie", plex_guid=item.guid)
            else:                                           tvdb_id, expired = self.Cache.get_tvdb_id("show", plex_guid=item.guid)
            if not tvdb_id and library.is_show:
                tmdb_id, expired = self.Cache.get_tmdb_id("show", plex_guid=item.guid)
                anidb_id, expired = self.Cache.get_anidb_id("show", plex_guid=item.guid)
        if expired or (not tmdb_id and library.is_movie) or (not tvdb_id and not tmdb_id and library.is_show):
            guid = requests.utils.urlparse(item.guid)
            item_type = guid.scheme.split(".")[-1]
            check_id = guid.netloc

            if item_type == "plex" and library.is_movie:
                for guid_tag in item.guids:
                    url_parsed = requests.utils.urlparse(guid_tag.id)
                    if url_parsed.scheme == "tmdb":                 tmdb_id = int(url_parsed.netloc)
                    elif url_parsed.scheme == "imdb":               imdb_id = url_parsed.netloc
            elif item_type == "imdb":                       imdb_id = check_id
            elif item_type == "thetvdb":                    tvdb_id = int(check_id)
            elif item_type == "themoviedb":                 tmdb_id = int(check_id)
            elif item_type == "hama":
                if check_id.startswith("tvdb"):             tvdb_id = int(re.search("-(.*)", check_id).group(1))
                elif check_id.startswith("anidb"):          anidb_id = re.search("-(.*)", check_id).group(1)
                else:                                       error_message = f"Hama Agent ID: {check_id} not supported"
            elif item_type == "myanimelist":                mal_id = check_id
            elif item_type == "local":                      error_message = "No match in Plex"
            else:                                           error_message = f"Agent {item_type} not supported"

            if not error_message:
                if anidb_id and not tvdb_id:
                    try:                                            tvdb_id = self.AniDB.convert_anidb_to_tvdb(anidb_id)
                    except Failed:                                  pass
                if anidb_id and not imdb_id:
                    try:                                            imdb_id = self.AniDB.convert_anidb_to_imdb(anidb_id)
                    except Failed:                                  pass
                if mal_id:
                    try:
                        ids = self.MyAnimeListIDList.find_mal_ids(mal_id)
                        if "thetvdb_id" in ids and int(ids["thetvdb_id"]) > 0:                  tvdb_id = int(ids["thetvdb_id"])
                        elif "themoviedb_id" in ids and int(ids["themoviedb_id"]) > 0:          tmdb_id = int(ids["themoviedb_id"])
                        else:                                                                   raise Failed(f"MyAnimeList Error: MyAnimeList ID: {mal_id} has no other IDs associated with it")
                    except Failed:
                        pass
                if mal_id and not tvdb_id:
                    try:                                            tvdb_id = self.MyAnimeListIDList.convert_mal_to_tvdb(mal_id)
                    except Failed:                                  pass
                if mal_id and not tmdb_id:
                    try:                                            tmdb_id = self.MyAnimeListIDList.convert_mal_to_tmdb(mal_id)
                    except Failed:                                  pass
                if not tmdb_id and imdb_id and isinstance(imdb_id, list) and self.TMDb:
                    tmdb_id = []
                    new_imdb_id = []
                    for imdb in imdb_id:
                        try:
                            temp_tmdb_id = self.TMDb.convert_imdb_to_tmdb(imdb)
                            tmdb_id.append(temp_tmdb_id)
                            new_imdb_id.append(imdb)
                        except Failed:
                            continue
                    imdb_id = new_imdb_id
                if not tmdb_id and imdb_id and self.TMDb:
                    try:                                            tmdb_id = self.TMDb.convert_imdb_to_tmdb(imdb_id)
                    except Failed:                                  pass
                if not tmdb_id and imdb_id and self.Trakt:
                    try:                                            tmdb_id = self.Trakt.convert_imdb_to_tmdb(imdb_id)
                    except Failed:                                  pass
                if not tmdb_id and tvdb_id and self.TMDb:
                    try:                                            tmdb_id = self.TMDb.convert_tvdb_to_tmdb(tvdb_id)
                    except Failed:                                  pass
                if not tmdb_id and tvdb_id and self.Trakt:
                    try:                                            tmdb_id = self.Trakt.convert_tvdb_to_tmdb(tvdb_id)
                    except Failed:                                  pass
                if not imdb_id and tmdb_id and self.TMDb:
                    try:                                            imdb_id = self.TMDb.convert_tmdb_to_imdb(tmdb_id)
                    except Failed:                                  pass
                if not imdb_id and tmdb_id and self.Trakt:
                    try:                                            imdb_id = self.Trakt.convert_tmdb_to_imdb(tmdb_id)
                    except Failed:                                  pass
                if not imdb_id and tvdb_id and self.Trakt:
                    try:                                            imdb_id = self.Trakt.convert_tmdb_to_imdb(tmdb_id)
                    except Failed:                                  pass
                if not tvdb_id and tmdb_id and self.TMDb and library.is_show:
                    try:                                            tvdb_id = self.TMDb.convert_tmdb_to_tvdb(tmdb_id)
                    except Failed:                                  pass
                if not tvdb_id and tmdb_id and self.Trakt and library.is_show:
                    try:                                            tvdb_id = self.Trakt.convert_tmdb_to_tvdb(tmdb_id)
                    except Failed:                                  pass
                if not tvdb_id and imdb_id and self.Trakt and library.is_show:
                    try:                                            tvdb_id = self.Trakt.convert_imdb_to_tvdb(imdb_id)
                    except Failed:                                  pass

                if (not tmdb_id and library.is_movie) or (not tvdb_id and not ((anidb_id or mal_id) and tmdb_id) and library.is_show):
                    service_name = "TMDb ID" if library.is_movie else "TVDb ID"

                    if self.TMDb and self.Trakt:                    api_name = "TMDb or Trakt"
                    elif self.TMDb:                                 api_name = "TMDb"
                    elif self.Trakt:                                api_name = "Trakt"
                    else:                                           api_name = None

                    if tmdb_id and imdb_id:                         id_name = f"TMDb ID: {tmdb_id} or IMDb ID: {imdb_id}"
                    elif imdb_id and tvdb_id:                       id_name = f"IMDb ID: {imdb_id} or TVDb ID: {tvdb_id}"
                    elif tmdb_id:                                   id_name = f"TMDb ID: {tmdb_id}"
                    elif imdb_id:                                   id_name = f"IMDb ID: {imdb_id}"
                    elif tvdb_id:                                   id_name = f"TVDb ID: {tvdb_id}"
                    else:                                           id_name = None

                    if anidb_id and not tmdb_id and not tvdb_id:    error_message = f"Unable to convert AniDb ID: {anidb_id} to TMDb ID or TVDb ID"
                    elif mal_id and not tmdb_id and not tvdb_id:    error_message = f"Unable to convert MyAnimeList ID: {mal_id} to TMDb ID or TVDb ID"
                    elif id_name and api_name:                      error_message = f"Unable to convert {id_name} to {service_name} using {api_name}"
                    elif id_name:                                   error_message = f"Configure TMDb or Trakt to covert {id_name} to {service_name}"
                    else:                                           error_message = f"No ID to convert to {service_name}"
            if self.Cache and (tmdb_id and library.is_movie) or ((tvdb_id or ((anidb_id or mal_id) and tmdb_id)) and library.is_show):
                if isinstance(tmdb_id, list):
                    for i in range(len(tmdb_id)):
                        util.print_end(length, f"Cache | {'^' if expired is True else '+'} | {item.guid:<46} | {tmdb_id[i] if tmdb_id[i] else 'None':<6} | {imdb_id[i] if imdb_id[i] else 'None':<10} | {tvdb_id if tvdb_id else 'None':<6} | {anidb_id if anidb_id else 'None':<5} | {mal_id if mal_id else 'None':<5} | {item.title}")
                        self.Cache.update_guid("movie" if library.is_movie else "show", item.guid, tmdb_id[i], imdb_id[i], tvdb_id, anidb_id, mal_id, expired)
                else:
                    util.print_end(length, f"Cache | {'^' if expired is True else '+'} | {item.guid:<46} | {tmdb_id if tmdb_id else 'None':<6} | {imdb_id if imdb_id else 'None':<10} | {tvdb_id if tvdb_id else 'None':<6} | {anidb_id if anidb_id else 'None':<5} | {mal_id if mal_id else 'None':<5} | {item.title}")
                    self.Cache.update_guid("movie" if library.is_movie else "show", item.guid, tmdb_id, imdb_id, tvdb_id, anidb_id, mal_id, expired)
        if tmdb_id and library.is_movie:                return "movie", tmdb_id
        elif tvdb_id and library.is_show:               return "show", tvdb_id
        elif (anidb_id or mal_id) and tmdb_id:          return "movie", tmdb_id
        else:
            util.print_end(length, f"{'Cache | ! |' if self.Cache else 'Mapping Error:'} {item.guid:<46} | {error_message} for {item.title}")
            return None, None
