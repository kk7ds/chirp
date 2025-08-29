{
  description = "Nix development environment";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    nixpkgs,
    flake-utils,
    ...
  }:
    flake-utils.lib.eachDefaultSystem (system: let
      pkgs = nixpkgs.legacyPackages.${system};
      pythonPackages = pkgs.python3Packages;
    in {
      devShells = {
        default = pkgs.mkShell {
          name = "impurePythonEnv";
          venvDir = "./.venv";

          # Packages required to build the venv
          buildInputs = [
            # The interpreter to use
            pythonPackages.python
            # automatically create the venv
            pythonPackages.venvShellHook
            # get nix to install wxpython as whl doesn't work on NixOS
            pythonPackages.wxpython

            pkgs.gsettings-desktop-schemas
            pkgs.glib
            pkgs.gtk3
          ];

          # Runtime packages
          packages = [
            # Python dev tools
            pythonPackages.ipython
            pythonPackages.ipdb
            pkgs.ruff
            pkgs.pyright

            # radio driver development dev tools
            pkgs.biodiff # binary diff
          ];
          env = {
            # Make breakpoint() use ipdb instead of the builtin pdb
            PYTHONBREAKPOINT = "ipdb.set_trace";

          };
          postVenvCreation = ''
            unset SOURCE_DATE_EPOCH
            # Install chirp as an editable package
            pip install -e .
          '';

          # Now we can execute any commands within the virtual environment.
          # This is optional and can be left out to run pip manually.
          postShellHook = ''
            # allow pip to install wheels
            unset SOURCE_DATE_EPOCH
            export XDG_DATA_DIRS=$GSETTINGS_SCHEMAS_PATH
          '';
        };
      };

      formatter = nixpkgs.legacyPackages.${system}.alejandra;
    });
}
