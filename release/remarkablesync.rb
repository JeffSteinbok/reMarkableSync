class Remarkablesync < Formula
  desc "Backup and convert reMarkable tablet notebooks to PDF"
  homepage "https://github.com/JeffSteinbok/RemarkableSync"
  url "https://github.com/JeffSteinbok/RemarkableSync/archive/refs/tags/v1.0.5.tar.gz"
  sha256 "e1a348eda2d66887add78cbd1e84865109e9a17081a75224654100c0cad5c240"
  license "MIT"
  head "https://github.com/JeffSteinbok/RemarkableSync.git", branch: "main"

  depends_on "pkgconf" => :build
  depends_on "cairo"
  depends_on "python@3.13"

  def install
    # Get the python dependency
    python3 = formula_opt_bin("python@3.13")/"python3.13"

    # Create virtualenv in libexec
    system python3, "-m", "venv", libexec

    # Install the package using pip in the virtualenv
    system libexec/"bin/pip", "install", "--upgrade", "pip", "setuptools", "wheel"
    system libexec/"bin/pip", "install", buildpath

    # Create bin wrappers
    bin.install_symlink libexec/"bin/reMarkableSync"
  end

  post_install_steps do
    on_macos do
      # Homebrew can rewrite Mach-O load commands during relocation.
      run "/bin/bash", args: ["-o", "pipefail", "-c", <<~SH, "sign-native-extensions", "{{libexec}}"]
        /usr/bin/find "$1" -type f -exec /usr/bin/file -E -0 -0 {} + |
          while IFS= read -r -d '' binary && IFS= read -r -d '' kind; do
            case "$kind" in
              *Mach-O*bundle*|*Mach-O*"shared library"*|*Mach-O*executable*)
                /usr/bin/codesign --force --sign - "$binary" || exit 1
                ;;
            esac
          done
      SH
    end
  end

  test do
    if OS.mac?
      # Include libraries in hidden wheel directories such as PIL/.dylibs.
      libexec.glob("**/*.{so,dylib}", File::FNM_DOTMATCH).each do |binary|
        system "/usr/bin/codesign", "--verify", binary
      end
    end

    # Test that the command runs and shows help
    assert_match "reMarkableSync", shell_output("#{bin}/reMarkableSync --help")

    # Test that rmc is available in the virtualenv
    system libexec/"bin/pip", "show", "rmc"
  end
end
